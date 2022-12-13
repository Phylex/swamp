import uhal
from typing import Union
from gbtsca_reset import sca_reset
from gbtsca_exception import GBT_SCA_I2C_Exception, GBT_SCA_ERROR
from gbtsca_constants import I2C_commands, I2C, SEU
from gbtsca_constants import I2C_ctrl_masks, I2C_frequencies, I2C_ERR
from gbtsca_constants import CTRL, ADC, ADC_commands
from gbtsca_constants import DAC, DAC_commands, GPIO
from gbtsca_constants import GPIO_commands
import sys
import threading
import asyncio
import struct
import logging


class Message:
    """ a message that is transmitted via the SCA """
    mID = 1

    def __init__(self, channel, command, data=bytearray()):
        self.id = Message.mID
        Message.mID += 1
        self.channel = channel
        self.command = command
        self.response_lock = threading.Lock()
        if len(data) <= 4:
            self.data = data
        else:
            raise ValueError("to many bytes in the transaction")

    async def send(self, sca, length_override=None):
        """ send sends the message via the SCA and blocks the
        task until a response is received upon reception of the
        message it continues the task and returns the response to
        the caller """
        logging.debug(
            "aquiring send lock for Message with mID {}".format(self.id))
        self.response_lock.acquire()
        sca.transmit(self, length_override)
        # wait for a response from the SCA
        logging.debug(
            "waiting for response for Msg with mID {}".format(self.id))
        self.response_lock.acquire()
        logging.debug(
            "received response for Msg with mID {}".format(self.id))
        self.response_lock.release()
        if self.error is not None:
            raise GBT_SCA_ERROR(error=self.error, channel=self.channel,
                                command=self.command)
        return self.response

    def receive_response(self, response, length, error=None):
        """
        receive the response that the message was waiting for and release
        the lock on that the processing task is waiting on
        """
        self.response_length = length
        self.response = response
        self.error = error
        logging.debug("released response_lock from mID = {}".format(self.id))
        self.response_lock.release()
        logging.debug("lock released")

    def __str__(self):
        str_repr = "Message:\n content: {}\n".format(self.data)\
            + "channel: 0x{:X}\n".format(self.channel)\
            + "command: 0x{:X}\n".format(self.command)
        if self.response_lock.locked():
            str_repr += "Waiting for a response"
        else:
            self.response = None
            str_repr += "With response:\n{}".format(self.response)
        return str_repr


class GBT_SCA:
    def __init__(self, basenode: str, confile=None, device=None, hwInterface=None, reset_gpio_address=None):
        uhal.setLogLevelTo(uhal.LogLevel.WARNING)
        try:
            if hwInterface is None:
                self.manager = uhal.ConnectionManager(confile)
                self.ipbushw = uhal.HwInterface(self.manager.getDevice(device))
            else:
                self.ipbushw = hwInterface

            # Check for GBT SCA without triggering uhal error message
            if(len(self.ipbushw.getNodes(basenode+".*")) == 0):
                raise GBT_SCA_ERROR(
                    str(sys._getframe().f_lineno) + " __init__" + " GBT-SCA " +
                    str(basenode) + " not found ")

            # define the transmit registers
            TX_NODE_SUFFIX = '-GBT-SCA-tx'
            self.tx_node = self.ipbushw.getNode(basenode+TX_NODE_SUFFIX)
            self.tx_addr = self.tx_node.getNode("address")
            self.tx_transaction_ID = self.tx_node.getNode("transID")
            self.tx_channel = self.tx_node.getNode("channel")
            self.tx_command = self.tx_node.getNode("command")
            self.tx_length = self.tx_node.getNode("length")
            self.tx_data = []
            self.tx_data.append(self.tx_node.getNode("data0"))
            self.tx_data.append(self.tx_node.getNode("data1"))
            self.tx_data.append(self.tx_node.getNode("data2"))
            self.tx_data.append(self.tx_node.getNode("data3"))
            self.tx_fifo_enable = self.tx_node.getNode("fifo_go")
            self.tx_fifo_fill = self.tx_node.getNode("fifo_fill")

            # define the receive registers
            RX_SUFFIX = '-GBT-SCA-rx'
            self.rx_node = self.ipbushw.getNode(basenode+RX_SUFFIX)
            self.rx_addr = self.rx_node.getNode("address")
            self.rx_transaction_ID = self.rx_node.getNode("transID")
            self.rx_channel = self.rx_node.getNode("channel")
            self.rx_control = self.rx_node.getNode("control")
            self.rx_length = self.rx_node.getNode("length")
            self.rx_data = []
            self.rx_data.append(self.rx_node.getNode("data0"))
            self.rx_data.append(self.rx_node.getNode("data1"))
            self.rx_data.append(self.rx_node.getNode("data2"))
            self.rx_data.append(self.rx_node.getNode("data3"))
            self.rx_error = self.rx_node.getNode("error")
            self.rx_pop = self.rx_node.getNode("pop")
            self.rx_dvaid = self.rx_node.getNode("rdatavalid")
            self.rx_interrupt = self.rx_node.getNode("interrupt")
            # as the reset is a bit more complicated it gets its own class
            if reset_gpio_address is None:
                raise ValueError("Please supply the address of the gpio"
                                 " module for the reset")
            self.reset = sca_reset(reset_gpio_address)

            # set the fifo up to continually send what it has in it's content
            self.tx_fifo_enable.write(1)
            self.tx_node.getClient().dispatch()

        except uhal.exception as uhalerr:
            print(uhalerr)
            raise GBT_SCA_ERROR(
                str(sys._getframe().f_lineno)+" __init__"+" GBT-SCA " +
                str(basenode) + " not found ")

        # queue and queue management
        self.transaction_queue_lock = threading.Lock()
        self.transaction_queue = []
        self.free_transaction_ids = list(range(1, 255))
        self.listener = None

        # instantiate the i2c busses
        self.i2c = [SCA_I2C(self, i) for i in range(16)]

        # instantiate the ADC
        self.adc = SCA_ADC(self)

        #instantiate the DAC
        self.dac = SCA_DAC(self)

        #instantiate the GPIO
        self.gpio = SCA_GPIO(self)

        # reset the chip
        self.reset.reset()
        # clear the rx fifo
        self.clear()

    def transmit(self, message: Message, length_override: int):
        """
        transmit a message to the gbtsca.

        Transmit a message and blocks until message is transmitted. The message is
        also added to the list of 'in-flight' transactions that the listener is waiting
        for a response to. If the listener is not running (and the queue of 'in-flight'
        messages empty) the listener is started.

        Args:
            message (Message): the message to be transmitted

            length_override : overrides the length of the data that gets sent
                              to the SCA
        """
        # start a listener, if it is not running yet or finished

        # generate a transaction ID that is valid and currently not in use
        self.transaction_queue_lock.acquire()
        logging.debug("transmit: acquired transaction_queue_lock")
        if len(self.free_transaction_ids) == 0:
            logging.error("No more free transaction IDs")
            raise GBT_SCA_ERROR("No more free transaction IDs")
        transaction_id = self.free_transaction_ids.pop(0)

        # put the data from the message into the proper registers
        # this is the SCA address so it does not change
        self.tx_addr.write(0)
        # now come the message content
        self.tx_channel.write(message.channel)
        self.tx_command.write(message.command)
        self.tx_transaction_ID.write(transaction_id)
        if length_override is not None:
            tx_length = length_override
        else:
            tx_length = len(message.data)
        self.tx_length.write(tx_length)
        for i, byte in enumerate(message.data):
            self.tx_data[i].write(byte)
        for i in range(len(message.data), 4):
            self.tx_data[i].write(0)

        # actually perform the load into the registers
        logging.info(
            "Sending Message:\n" +
            "\tAddress: {}".format(0) +
            "\t\t\tTransaction ID: {}".format(transaction_id) +
            "\tChannel: 0x{:X}".format(message.channel) +
            "\tCommand: 0x{:X}".format(message.command) +
            "\tlength: {}".format(tx_length) +
            "\tdata: {}".format([i for i in message.data]))
        self.tx_node.getClient().dispatch()

        # push the registers into the fifo
        self.tx_fifo_fill.write(1)
        self.tx_node.getClient().dispatch()
        self.transaction_queue.append((transaction_id, message))
        logging.debug("transmit: releasing transaction_queue_lock")
        self.transaction_queue_lock.release()
        # the listener is not allowed to run without in-flight messages
        if self.listener is None or (not self.listener.is_alive()):
            logging.debug(
                "transmit: Listener is inactive, activating listener")
            self.listener = threading.Thread(target=self.listen).start()
        return

    def listen(self):
        """
        listen for incoming responses from the gbtsca

        listen for incoming responses from the gbtsca and associate them with
        the transmitted messages using the transaction ID.

        The listener expects that there is a task that is waiting for the
        send-lock of the message to be released. If this is not the case the
        message will be dropped after the response is received as the only
        reference to the message will be dropped after receiving the response

        In case of an error the error field of the message is filled with the
        appropriate code and no data is written. The user code has to decide
        how to procede with the error.

        Args:
            none : The listen function will release a lock that was acquired
                   as the message was transmitted so that the task that is
                   waiting for the lock can resume. It is expected that
                   there is a task that waits for a response.
        Returns:
            nothing
        """
        while True:
            self.wait_for_valid_rx()
            address = self.rx_addr.read()
            channel = self.rx_channel.read()
            transID = self.rx_transaction_ID.read()
            control = self.rx_control.read()
            length = self.rx_length.read()
            error = self.rx_error.read()
            data = [d.read() for d in self.rx_data]
            self.rx_node.getClient().dispatch()

            # we have to prevent the transmit function from altering the transaction
            # list
            self.transaction_queue_lock.acquire()
            if transID.value() == 0 or transID.value() == 255:
                logging.warn(
                    "Received Message with invalid TID:\n" +
                    "\tAddress: {}".format(address.value()) +
                    "\tControl: {}".format(control.value()) +
                    "\tTransaction ID: {}".format(transID.value()) +
                    "\tChannel: 0x{:X}".format(channel.value()) +
                    "\tError: 0x{:X}".format(error.value()) +
                    "\tlength: {}".format(length.value()) +
                    "\tdata: {}".format([d.value() for d in data]))
                # clear bad message
                logging.debug("listen: removing message from rx fifo")
                self.rx_pop.write(1)
                self.rx_node.getClient().dispatch()
                # release the lock
                logging.debug("listen: releasing transaction_queue_lock")
                self.transaction_queue_lock.release()
                continue

            # read the data in the response
            resp_data = bytearray([d.value() for d in data])
            logging.info("listen: Received a Response:\n" +
                         "\tAddress: {}".format(address.value()) +
                         "\tControl: {}".format(control.value()) +
                         "\tTransaction ID: {}".format(transID.value()) +
                         "\tChannel: 0x{:X}".format(channel.value()) +
                         "\tError: 0x{:X}".format(error.value()) +
                         "\tlength: {}".format(length.value()) +
                         "\tdata: {}".format([i for i in resp_data]))

            # check which of the transactions the response belongs to
            transaction_list = list(filter(lambda t: t[0] == transID.value(),
                                           self.transaction_queue))
            if len(transaction_list) != 1:
                error_msg = ""
                error_msg += "Got a response for a message that was not"
                error_msg += " listed as an open transaction\n"
                error_msg += "\tTransaction ID: {}".format(transID.value())
                error_msg += "\tError Code: 0x{:X}".format(error.value())
                error_msg += "\tData: {}".format([d.value() for d in data])
                logging.error(error_msg)
                raise GBT_SCA_ERROR(error_msg)
            else:
                transaction = transaction_list[0]
                self.free_transaction_ids.append(transaction[0])
            logging.debug(
                "listen: found matching message: {}".format(transaction))
            self.transaction_queue = list(
                filter(lambda t: t[0] != transID.value(),
                       self.transaction_queue))
            logging.debug(
                "listen: transaction queue after removing " +
                "{}:\n{}".format(transaction, self.transaction_queue))
            # check for differing addresses/channels in the response
            message = transaction[1]
            if message.channel != channel.value():
                error_msg = "listen: Channel mismatch"\
                    " with in: \n{}".format(message)
                logging.error(error_msg)
                raise GBT_SCA_ERROR(error_msg)
            if address.value() != 0:
                error_msg = "listen: The Address in the"\
                    " response was not 0 but {}".format(
                            address.value())
                logging.error(error_msg)
                raise GBT_SCA_ERROR(error_msg)

            # read in the data from the data registers and put it together
            # to a byte array
            # deal with an error in the received response by passing it
            # to the user task to deal with, leaving this task running
            if error.value() == 0:
                message.receive_response(resp_data, length.value())
            else:
                message.receive_response(bytearray(), 0, error=error.value())

            # pop the top of the fifo after having read it
            logging.debug("listen: removing message from rx fifo")
            self.rx_pop.write(1)
            self.rx_node.getClient().dispatch()

            # if there are no more messages 'in flight' stop listening
            logging.debug("listen: releasing transaction_queue_lock")
            if len(self.transaction_queue) == 0:
                logging.debug("listen: Transaction queue empty" +
                              " shutting down")
                self.transaction_queue_lock.release()
                break
            else:
                self.transaction_queue_lock.release()

    def clear(self):
        """
        Clear the Rx-FiFo buffer. Do this during construction of the gbtsca
        object
        """
        clear = False
        logging.debug("clearing the rx buffer")
        while not clear:
            dvalid = self.rx_dvaid.read()
            self.tx_node.getClient().dispatch()
            logging.debug("fetched a dvaild = {}".format(dvalid.value()))
            if dvalid.value() == 1:
                self.rx_pop.write(1)
                self.rx_node.getClient().dispatch()
            else:
                clear = True
        logging.debug("done cleaning")

    async def spawn_listener(self):
        """
        wrap the listener task (that runs in an executor) in a normal

        asyncio task that the loop waits for before shutting down



        As the listener will exit as soon as there are no more messages
        to listen to this task will end after the response to the
        last message has been sent
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.listen)

    def wait_for_valid_rx(self):
        """
        Wait until the rx-fifo has a message for us to read

        the rx-fifo has an interrupt that blocks the running
        thread until the fifo has
        """
        # check if ther still are packets in the fifo
        dvalid = self.rx_node.getNode("rdatavalid").read()
        self.rx_node.getClient().dispatch()
        logging.debug("wait_for_valid_rx: read dvaid as" +
                      " {}".format(dvalid.value()))
        if dvalid.value() == 1:
            return
        # as the fifo is empty wait for the interrupt
        logging.debug("wait_for_vaild_rx: waiting for rx interrupt")
        _ = self.rx_interrupt.read()
        self.rx_node.getClient().dispatch()
        # check rdatavalid to catch an error state
        dvalid = self.rx_dvaid.read()
        self.rx_node.getClient().dispatch()
        # after a read there should be data there so
        # if there is not throw an error
        if dvalid.value() == 0:
            raise GBT_SCA_ERROR("Woke from read interrupt to find empty FIFO")
        # dvalid was fine so continue with reading the response
        return

    async def readDeviceID(self, v2=False):
        """ Read the device ID of the GBTSCA

        Read the device ID by sending a message to the GBTSCA and waiting for
        the response.

        Args:
            v2 (bool): select if it is a V2 chip (True) or a V1 chip (False)

        Returns:
            id (int): the ID of the SCA
        """
        if(v2):
            command_str = "ID_v2"
        else:
            command_str = "ID_v1"
        if not self.adc.enabled:
            disable_adc = True
            await self.adc.enable()
        message = Message(channel=ADC["channel"],
                          command=ADC_commands[command_str],
                          data=bytearray())
        response = await message.send(sca=self)
        if disable_adc:
            await self.adc.disable()
        return struct.unpack('<i', response)[0]

    async def enableDevice(self, register, bitmask):
        """
        enable the a peripheral of the SCA

        Note: The interface is enabled in the control registers and as
        only one bit is to be set the procedure needs to be a read-
        modify-write
        """
        logging.debug("enabling device in reg {}:{}".format(register, bitmask))
        read_enable_reg_msg = Message(command=CTRL['R_CR'+register],
                                      channel=CTRL['channel'])
        config_reg = await read_enable_reg_msg.send(self)
        config_reg = config_reg[3] | bitmask
        data = bytearray([0, 0, 0])
        data.append(config_reg)
        write_enable_reg_msg = Message(command=CTRL['W_CR'+register],
                                       channel=CTRL['channel'],
                                       data=data)
        await write_enable_reg_msg.send(self, 0)

    async def disableDevice(self, register, bitmask):
        """
        disable a peripheral of the SCA

        Note: The interface is disabled in the control registers and as
        only one bit is to be set the procedure needs to be a read-
        modify-write
        """
        logging.debug("disabling device in" +
                      " reg {}:{}".format(register, bitmask))
        read_enable_reg_msg = Message(command=CTRL['R_CR'+register],
                                      channel=CTRL['channel'])
        config_reg = await read_enable_reg_msg.send(self)
        config_reg = (config_reg[3] & (~bitmask & 0xff))
        data = bytearray([0, 0, 0, config_reg])
        write_enable_reg_msg = Message(command=CTRL['W_CR'+register],
                                       channel=CTRL['channel'],
                                       data=data)
        await write_enable_reg_msg.send(self, 0)


class SCA_ADC:
    def __init__(self, sca: GBT_SCA):
        """
        build the object that acts as a software representation
        for the ADC controller in the SCA

        Args:
            sca (GBT_SCA): Tell the ADC which SCA it belongs to

        Note:
            The ADC class will normally be instantiated by the sca.
        """

        self.sca = sca
        self.enable_register = ADC['enable_register']
        self.enable_bit = ADC['enable_bit']
        self.enabled = False

    async def enable(self):
        await self.sca.enableDevice(self.enable_register, self.enable_bit)
        self.enabled = True

    async def disable(self):
        await self.sca.disableDevice(self.enable_register, self.enable_bit)
        self.enabled = False

    async def select_input(self, channel):
        """
        Set in the adc mux register to the chosen channel.

        Args:
            channel (int): ADC channel to set from (0-31). 

        Raises:
            GBT_SCA_ERROR: If the adc requested ADC channel is out of range.
        """       
        if not self.enabled:
            self.enable()
        if channel not in range(32):
            logging.error("Invalid channel requested for ADC mux, received request for "+channel)
            raise GBT_SCA_ERROR("Invalid channel requested for ADC mux, received request for "+channel)
        data = bytearray([channel, 0, 0, 0])
        logging.debug("writing adc mux reg to %s " % channel)
        set_adc_mux_msg = Message(command=ADC_commands['W_MUX'],
                                  channel=ADC['channel'],
                                  data=data)
        _ = await set_adc_mux_msg.send(self.sca)

    async def read(self, channel=None):
        """
        Read the current value of a given ADC channel or the current channel 
        set in the adc mux register.

        Args:
            channel (int): ADC channel to read from (0-31). 

        Returns:
            value (int): Value read from the requested ADC channel.

        Raises:
            GBT_SCA_ERROR: If the adc requested ADC channel is out of range.
        """       
        if not self.enabled:
            await self.enable()
        if channel is not None:
            await self.select_input(channel)
        data = bytearray([1, 0, 0, 0])
        logging.debug("Reading adc output register")
        read_adc_reg = Message(command=ADC_commands['GO'],
                               channel=ADC['channel'],
                               data=data)
        response = await read_adc_reg.send(self.sca)
        return response[0]


class SCA_DAC:
    def __init__(self, sca: GBT_SCA):
        """
        build the object that acts as a software representation
        for the DAC controller in the SCA

        Args:
            sca (GBT_SCA): Tell the DAC which SCA it belongs to

        Note:
            The DAC class will normally be instantiated by the sca.
            This class represents four independent DAC channels 
            (A,B,C, and D) which share a common enable bit.
        """
        self.sca = sca
        self.enable_register = DAC['enable_register']
        self.enable_bit = DAC['enable_bit']
        self.enabled = False

    async def set(self, channel, voltage):
        """
        Set a DAC channel to a voltage (0-1V) with 256 bit precision.
        Rounds to nearest possible voltage value. 

        Args:
            channel (str): DAC channel to write to (A,B,C, or D). 
            value (int): Voltage to set the DAC to. Range 0-1V.

        Raises:
            GBT_SCA_ERROR: If the requested channel is not one
            of the allowed channels or the voltage is outside 
            of the allowed range set raises an error and
            prints the requested channel and voltage.
        """
        if voltage < 0. or voltage > 1.:
            logging.error("Invalid voltage requested for DAC, received request for voltage of "+str(voltage))
            raise GBT_SCA_ERROR("Invalid voltage requested for DAC, received request for voltage of "+str(voltage))
        adcval = int(voltage*256+0.5)
        if adcval>255:
            adcval=255
        await self.write(channel,adcval)

    async def enable(self):
        """
        enable the dac interface

        note: the control register sets the dac enable using
        one specific bit, so the procedure needs to be read-modify-write
        to avoid changing other settings.
        """
        await self.sca.enableDevice(self.enable_register, self.enable_bit)
        self.enabled = True

    async def disable(self):
        """
        disable the DAC interface

        Note:  The control register sets the DAC enable using
        one specific bit, so the procedure needs to be read-modify-write
        to avoid changing other settings.
        """
        await self.sca.disableDevice(self.enable_register, self.enable_bit)
        self.enabled = False

    async def write(self, channel, value):
        """
        Set a DAC channel to a integer value

        Args:
            channel (str): DAC channel to write to (A,B,C, or D). 
            value (int): Value to set DAC to. Range 0-255.

        Raises:
            GBT_SCA_ERROR: If the requested channel is not one
            of the allowed channels write raises an error and
            prints the requested channel.
        """
        channel = channel.upper()
        if channel in DAC['channels']:
            command = f"W_{channel}"
        else:
            logging.error("Invalid channel requested for DAC write, received request for "+channel)
            raise GBT_SCA_ERROR("Invalid channel requested for DAC write, received request for "+channel)
        data = bytearray([0, 0, 0, value])
        logging.debug("setting dac channel %s to %s" % (channel, value))
        write_dac_reg_msg = Message(command=DAC_commands[command],
                                    channel=DAC['channel'],
                                    data=data)
        _ = await write_dac_reg_msg.send(self.sca)

    async def read(self, channel):
        """
        Read the current value of a given DAC channel

        Args:
            channel (str): DAC channel to read from (A,B,C, or D). 

        Returns:
            value (int): Value read from the requested channel.

        Raises:
            GBT_SCA_ERROR: If the requested channel is not one
            of the allowed channels read raises an error and
            prints the requested channel.
        """       
        channel = channel.upper()
        if channel in DAC['channels']:
            command = f"R_{channel}"
        else:
            logging.error("Invalid channel requested for DAC read, received request for "+channel)
            raise GBT_SCA_ERROR("Invalid channel requested for DAC read, received request for "+channel)
        logging.debug("reading dac channel %s " % channel)
        read_dac_reg_msg = Message(command=DAC_commands[command],
                                   channel=DAC['channel'])
        dac_reg = await read_dac_reg_msg.send(self.sca)
        return dac_reg[3]

class SCA_GPIO:
    def __init__(self, sca: GBT_SCA):
        """
        build the object that acts as a software representation
        for the GPIO controller in the SCA

        Args:
            sca (GBT_SCA): Tell the GPIO which SCA it belongs to

        Note:
            The GPIO class will normally be instantiated by the sca.
        """
        self.sca = sca
        self.enable_register = GPIO['enable_register']
        self.enable_bit = GPIO['enable_bit']
        self.channel = GPIO['channel']
        self.enabled = False
        self.dataout = 0
        self.datain = 0
        self.direction = 0
        self.interrupt_enable = 0
        self.interrupt_select = 0
        self.int_edge_select = 0
        self.interrupts = 0
        self.clock_select = 0
        self.edge_select = 0
        self.pins = [SCA_GPIO_Pin(self, i) for i in range(32)]

    async def enable(self):
        """
        enable the gpio interface

        note: the control register sets the spio enable using
        one specific bit, so the procedure needs to be read-modify-write
        to avoid changing other settings.
        """
        await self.sca.enableDevice(self.enable_register, self.enable_bit)
        self.enabled = True

    async def disable(self):
        """
        disable the GPIO interface

        Note:  The control register sets the GPIO enable using
        one specific bit, so the procedure needs to be read-modify-write
        to avoid changing other settings.
        """
        await self.sca.disableDevice(self.enable_register, self.enable_bit)
        self.enabled = False

    async def read_all_gpios(self):
        """
        read the gpio state of all pins at the same time
        """
        gpios = Message(self.channel,
                        GPIO_commands["R_DATAIN"],
                        bytearray([0, 0, 0, 0]))
        response = await gpios.send(self.sca)
        self.datain = struct.unpack("<I", response)[0]

    async def set_directions(self, directions, mask=0xffff):
        """
        Set direction of gpios chosen with mask
        """
        self.direction=((~mask)&self.direction)|(mask&directions)
        setting = Message(self.channel,
                          GPIO_commands["W_DIRECTION"],
                          bytearray([0xff&self.direction,0xff&self.direction>>8,0xff&self.direction>>16,self.direction>>24]))
        response = await setting.send(self.sca)
        for pin in self.pins:
           pin.direction=0x1&(self.direction>>pin.number)
        
    async def get_directions(self):
        """
        Read gpio directions from gbt-sca instead of local cache
        """
        gbtsca_directions = Message(self.channel,
                                   GPIO_commands["R_DIRECTION"],
                                   bytearray())
        response = await gbtsca_directions.send(self.sca)
        self.directions = struct.unpack("<I", response)[0]
        for pin in self.pins:
           pin.direction=0x1&(self.direction>>pin.number)
        return self.directions

    async def set_outputs(self, output, mask=0xffff):
        """
        Set output of gpios chosen with mask
        """
        self.dataout=((~mask)&self.dataout)|(mask&output)
        setting = Message(self.channel,
                                GPIO_commands["W_DATAOUT"],
                                bytearray([0xff&self.dataout,0xff&self.dataout>>8,0xff&self.dataout>>16,self.dataout>>24]))

        response = await setting.send(self.sca)
        for pin in self.pins:
           pin.output=0x1&(self.dataout>>pin.number)

    async def read_outputs(self):
       """
       Read gpio outputs from gbt-sca instead of local cache
       """
       gbtsca_outputs = Message(self.channel,
                                      GPIO_commands["R_DATAOUT"],
                                      bytearray())
       response = await gbtsca_outputs.send(self.sca)
       self.dataout = struct.unpack("<I", response)[0]
       for pin in self.pins:
          pin.output=0x1&(self.dataout>>pin.number)
       return self.dataout

    async def enable_interrupts(self):
       """
       Enable interrupt generation for gpio
       """
       enable = Message(self.channel,
                        GPIO_commands["W_INT_ENABLE"],
                        bytearray([1,0,0,0]))
       await enable.send(self.sca)
       self.interrupt_enable=1
 
    async def disable_interrupts(self):
       """
       Disable interrupt generation for gpio
       """
       disable = Message(self.channel,
                         GPIO_commands["W_INT_ENABLE"],
                         bytearray([0,0,0,0]))
       await disable.send(self.sca)
       self.interrupt_enable=0

    async def select_interrupts(self, interrupts, mask):
       """
       Set interrupts provided with mask
       """
       self.interrupt_select =((~mask)&self.interrupt_select)|(mask&interrupts)

       interrupt_command = Message(self.channel,
                                   GPIO_commands["W_INT_SEL"],
                                   bytearray([0xff&self.interrupt_select,0xff&self.interrupt_select>>8,0xff&self.interrupt_select>>16,0xff&self.interrupt_select>>24]))
       interrupts_selected = await interrupt_command.send(self.sca)
       for pin in self.pins:
         pin.generate_interrupt=0x1&(self.interrupt_select>>pin.number)

       return self.interrupt_select
    
    async def read_interrupt_select(self):
       """
       Read interrupts set from gbt-sca and update local cache
       """
       interrupt_read_command = Message(self.channel,
                                        GPIO_commands["R_INT_SEL"],
                                        bytearray())
       interrupts_selected = await interrupt_read_command.send(self.sca)
       self.interrupt_select = struct.unpack("<I", interrupts_selected)[0]
       for pin in self.pins:
         pin.generate_interrupt=0x1&(self.interrupt_select>>pin.number)

       return self.interrupt_select
 
    async def set_interrupt_edge(self, interrupt_edges, mask):
       """
       Set interrupt rising/falling edge provided with mask
       """
       self.int_edge_select =((~mask)&self.int_edge_select)|(mask&interrupt_edges)
       int_edge_command = Message(self.channel,
                                      GPIO_commands["W_INT_TRIG"],
                                      bytearray([0xff&self.int_edge_select,0xff&self.int_edge_select>>8,0xff&self.int_edge_select>>16,0xff&self.int_edge_select>>24]))
       int_edge_selected = await int_edge_command.send(self.sca)
       for pin in self.pins:
         pin.interrupt_edge=0x1&(self.int_edge_select>>pin.number)

       return self.int_edge_select
    
    async def read_interrupt_edge(self):
       """
       Read interrupts edges set from gbt-sca and update local cache
       """
       int_edge_read = Message(self.channel,
                               GPIO_commands["R_INT_TRIG"],
                               bytearray())
       int_edge_selected = await int_edge_read.send(self.sca)
       self.int_edge_select = struct.unpack("<I", int_edge_selected)[0]
       for pin in self.pins:
         pin.interrupt_edge=0x1&(self.int_edge_select>>pin.number)

       return self.int_edge_select

    async def set_interrupt_state(self, interrupt_state, mask):
       """
       Set vector of gpio status during last generated interrupt
       """
       self.interrupts =((~mask)&self.interrupts)|(mask&interrupt_state)
       interrupt_set_command = Message(self.channel,
                                       GPIO_commands["W_INTS"],
                                       bytearray([0xff&self.interrupts,0xff&self.interrupts>>8,0xff&self.interrupts>>16,0xff&self.interrupts>>24]))
       await interrupt_set_command.send(self.sca)
       for pin in self.pins:
         pin.interrupt_state=0x1&(self.interrupts>>pin.number)

       return self.interrupts
    
    async def read_interrupt_state(self):
       """
       Read state of gpios during last generated interrupt and save to local cache
       """
       interrupt_read_command = Message(self.channel,
                                        GPIO_commands["R_INTS"],
                                        bytearray())
       interrupt_state = await interrupt_read_command.send(self.sca)
       self.interrupts = struct.unpack("<I", interrupt_state)[0]
       for pin in self.pins:
         pin.interrupt_state=0x1&(self.interrupts>>pin.number)

       return self.interrupts

    async def set_clk_sel(self, clk_sel, mask):
       """
       Select if gpio input/output is latched to internal clk (0) or external strobe (1)
       """
       self.clock_select =((~mask)&self.clock_select)|(mask&clk_sel)
       clock_select_command = Message(self.channel,
                                      GPIO_commands["W_CLKSEL"],
                                      bytearray([0xff&self.clock_select,0xff&self.clock_select>>8,0xff&self.clock_select>>16,0xff&self.clock_select>>24]))
       await clock_select_command.send(self.sca)
       for pin in self.pins:
         pin.use_external_clock=0x1&(self.clock_select>>pin.number)

       return self.clock_select
    
    async def read_clk_sel(self):
       """
       Read selected clocks
       """
       clk_sel_read = Message(self.channel,
                              GPIO_commands["R_CLKSEL"],
                              bytearray())
       clk_sel = await clk_sel_read.send(self.sca)
       self.clock_select = struct.unpack("<I", clk_sel)[0]
       for pin in self.pins:
         pin.use_external_clock=0x1&(self.clock_select>>pin.number)

       return self.clock_select
 
    async def set_edge_sel(self, edge_sel, mask):
       """
       Select if gpio input/output is latched to on rising (0) or falling (1) clock edge
       """
       self.edge_select =((~mask)&self.edge_select)|(mask&edge_sel)
       edge_select_command = Message(self.channel,
                                     GPIO_commands["W_EDGESEL"],
                                     bytearray([0xff&self.edge_select,0xff&self.edge_select>>8,0xff&self.edge_select>>16,0xff&self.edge_select>>24]))
       await edge_select_command.send(self.sca)
       for pin in self.pins:
         pin.sampling_edge=0x1&(self.edge_select>>pin.number)

       return self.edge_select
    
    async def read_edge_sel(self):
       """
       Read edge select register from gbtsca and update cache
       """
       clk_sel_read = Message(self.channel,
                              GPIO_commands["R_EDGESEL"],
                              bytearray())
       clk_sel = await clk_sel_read.send(self.sca)
       self.edge_select = struct.unpack("<I", clk_sel)[0]
       for pin in self.pins:
         pin.sampling_edge=0x1&(self.edge_select>>pin.number)

       return self.edge_select

class SCA_GPIO_Pin:
    def __init__(self, gpio_block: SCA_GPIO, number):
        self.gpio_block = gpio_block
        self.number = number
        self.direction = 0
        self.sampling_edge = 0
        self.generate_interrupt = 0
        self.interrupt_edge = 0
        self.use_external_clock = 0 
        self.output = 0

    async def set_direction(self, direction: str):
        """
        Set the direction of the gpio pin to "in" or "out"
        """
        direction = direction.lower()
        if direction != "in" and direction != "out":
            raise GBT_SCA_ERROR("direction must be either 'in' or 'out'")
        if direction == "in":
            await self.gpio_block.set_directions(0,0x1<<self.number)
        else:
            await self.gpio_block.set_directions(1<<self.number,0x1<<self.number)
   
    async def set_output(self, value):
        """
        Set the output of the gpio pin to 1 or 0
        """
        if not self.direction:
            await self.set_direction("out")
        await self.gpio_block.set_outputs(value<<self.number,0x1<<self.number)

    async def set_interrupt(self, value: bool):
        """
        Enable/disable the interrupt for the chosen pin. Enables the gpio interrupt and sets pin to input if necessary.
        """
        if value:
            if self.direction:
                await self.set_direction("in")
            if not self.gpio_block.interrupt_enable:
                await self.gpio_block.enable_interrupts()
        await self.gpio_block.select_interrupts(value<<self.number,0x1<<self.number)

    async def set_interrupt_edge(self, value: bool):
        """
        Set the pin to trigger interrupts on rising (0) or falling (1) edge.
        """
        await self.gpio_block.set_interrupt_edge(value<<self.number,0x1<<self.number)

    async def ext_clk_sel(self, value: bool):
        """
        Select whether the pin is latched to internal (0) or external (1) clock signal.
        """
        await self.gpio_block.set_clk_sel(value<<self.number,0x1<<self.number)

    async def edge_sel(self, value: bool):
        """
        Select whether the pin latches its input/output on the rising (0) or falling (1) clock signal.
        """
        await self.gpio_block.set_edge_sel(value<<self.number,0x1<<self.number)

    async def read_int_state(self):
        """
        Returns the state of the gpio during the last generated interrupt.
        """
        state = await self.gpio_block.read_interrupt_state()
        return (state>>self.number)&0x1

class SCA_I2C:
    def __init__(self, sca: GBT_SCA, index: int):
        """
        build the object that acts as software representation
        for a I2C master in the SCA

        Args:
            sca (GBT_SCA): pass that in to tell the I2C to which SCA it belongs

            index (int): integer in the range from 0 to 15 to indicate which of
                         the 16 I2C masters the object is associated to

        Note:
            The I2C class will be normally be instantiated by the gbtsca and
            should normally not be called by user code directly
        """
        self.sca = sca
        if index < 0 or index > 15:
            raise ValueError("Index for GBT_SCA I2C channel out of range"
                             "\nvalid range is 0 - 15")
        self.index = index
        # check gbtsca_constants for the constants referenced here
        self.channel = I2C[index]['channel']
        self.enable_register = I2C[index]['enable_register']
        self.enable_bit = I2C[index]['enable_bit']

    async def enable(self, i2c_bus_frequency=None):
        """
        enable the I2C interface

        Args:
            i2c_bus_frequency: select the frequency of the i2c bus. the possible
            vaules are 100, 200, 400 and 1000 and indicate the bus frequency in
            Kiloherz.

        Note: The interface is enabled in the control registers and as
        only one bit is to be set the procedure needs to be a read-
        modify-write during the enabling process the control register is read and the
        state of the device is updated
        """
        await self.sca.enableDevice(self.enable_register, self.enable_bit)
        if i2c_bus_frequency is not None:
            if i2c_bus_frequency not in [100, 200, 400, 1000]:
                raise GBT_SCA_I2C_Exception(
                    "the bus frequency is not one of the permissible vaules")
            self._set_bus_frequency(i2c_bus_frequency)

    async def _set_bus_frequency(self, frequency: int):
        """
        set the i2c bus frequency.

        This is an internal function and should not be called by user
        code.

        """
        ctrl_msg = await Message(channel=self.channel,
                                 command=I2C_commands['R_CTRL_REG']
                                 ).send(self.sca)
        ctrl_msg = ctrl_msg & I2C_ctrl_masks['freq'] | I2C_frequencies[frequency]
        await Message(channel=self.channel,
                      command=I2C_commands['W_CTRL_REG']).send

    async def disable(self):
        """
        disable the I2C interface

        Note: The interface is disabled in the control registers and as
        only one bit is to be set the procedure needs to be a read-
        modify-write
        """
        await self.sca.disableDevice(self.enable_register, self.enable_bit)

    def _check_i2c_status(self, response):
        i2c_status = response[3]
        if i2c_status & 0x4 == 0:
            raise GBT_SCA_I2C_Exception(i2c_status, self.index)

    async def write_byte(self, address: int, byte: int):
        """
        write a single byte to to the specified address

        Args:
            address (int): address on the i2c bus to write the byte to.
                           range 0 to 127

            byte (int): the value.the value has to be in the
                        range 0 to 255

        Raises:
            GBT_SCA_I2C_Exception: If the status flag shows an unsuccessful
            transaction it raises an error and prints the received
            status
        """
        data = bytearray([0, 0, byte, address])
        msg = Message(channel=self.channel,
                      command=I2C_commands['W_7B_SINGLE'], data=data)
        resp = await msg.send(self.sca)
        self._check_i2c_status(resp)

    async def read_byte(self, address: int):
        """
        Read a single byte from the specified address

        Args:
            address (int): address to read from. range 0-127

        Returns:
            value (int): value read from the given address
                         as unsigned integer

        Raises:
            GBT_SCA_I2C_Exception: if the status flags show an
            unsuccessful transaction it raises an error and prints the
            received status
        """
        data = bytearray([0, 0, 0, address])
        msg = Message(channel=self.channel,
                      command=I2C_commands['R_7B_SINGLE'], data=data)
        resp = await msg.send(self.sca)
        value = resp[2]
        self._check_i2c_status(resp)
        return value

    async def _write_block(self, data: bytearray, REG: int):
        """
        Write a block of four data bytes into the Tx/Rx buffer of the SCA

        Args:
            data (bytearray): the four bytes of data to send
            REG (int): the number of the Register of the buffer
        """
        command = "W_DATA_{}".format(REG)
        if command not in I2C_commands.keys():
            raise GBT_SCA_ERROR("Command issued is not in i2c command set")
        msg = Message(channel=self.channel,
                      command=I2C_commands[command],
                      data=data)
        await msg.send(self.sca)

    async def write(self, address: int, data: bytearray):
        """
        write up to 16 consecutive bytes in one I2C transaction
        """
        if len(data) > 16:
            raise GBT_SCA_ERROR("To manny bytes passed into"
                                "SCA write operation")
        tx_len = len(data)
        # pad uneven data with trailing zeros
        remaining_bytes = len(data) % 4
        for i in range(4-remaining_bytes):
            data.append(0)
        # send the data blockwise into the SCA write data storage
        block_writes = len(data) // 4
        for i in range(block_writes):
            tx_data = data[i*4:(i+1)*4]
            tx_data.reverse()
            await self._write_block(tx_data, i)
        # set the number of bytes to write in the control register field
        ctrl = await Message(self.channel,
                             I2C_commands["R_CTRL_REG"]).send(self.sca)
        ctrl = ctrl[3]
        # set the bits of the control register to show number of tx_bytes
        ctrl &= (~CTRL["NBYTE_MASK"] & 0xff)
        ctrl |= (CTRL["NBYTE_MASK"] & (tx_len << 2))
        await Message(self.channel,
                      I2C_commands["W_CTRL_REG"],
                      bytearray([0, 0, 0, ctrl])).send(self.sca)
        # construct the message that starts the 16 byte transmit
        trx_msg = await Message(self.channel,
                                I2C_commands["W_7B_MULTI"],
                                bytearray([0, 0, 0, address])).send(self.sca)
        self._check_i2c_status(trx_msg)

    async def _read_block(self, reg: int):
        """
        Reads a block of 4 bytes from the I2C tx/rx buffer register

        Args:
            reg (int): the number of the registers to read from

        Returns:
            data (bytearray): the data read from the registers formatted into
                              the 'natural' order (the reverse from what is
                              in the SCA datasheet)
        """
        command = "R_DATA_{}".format(reg)
        if command not in I2C_commands.keys():
            raise GBT_SCA_ERROR("Command issued is not in i2c command set")
        msg = Message(channel=self.channel,
                      command=I2C_commands[command])
        rx_data = await msg.send(self.sca)
        rx_data.reverse()
        return rx_data

    async def read(self, address: int, bytecount: int):
        """
        Read up to 16 consecutive bytes from the given address

        Args:
            address (int): address to read from (range from 0 to 127)
            bytecount (int): number of bytes to read (range from 1 to 16)

        Returns:
            rx_data (bytearray): data read from the target address on the bus
        """
        if bytecount > 16 or bytecount < 1:
            raise GBT_SCA_ERROR("Invald amount of bytes to read via the I2C")
        if bytecount == 1:
            return bytearray([await self.read_byte(address)])
        # set the number of bytes to read
        ctrl = await Message(self.channel,
                             I2C_commands["R_CTRL_REG"]).send(self.sca)
        ctrl = ctrl[3]
        # set the bits of the control register to show number of tx_bytes
        ctrl &= (~CTRL["NBYTE_MASK"] & 0xff)
        ctrl |= (CTRL["NBYTE_MASK"] & (bytecount << 2))
        await Message(self.channel,
                      I2C_commands["W_CTRL_REG"],
                      bytearray([0, 0, 0, ctrl])).send(self.sca)
        # Send the read command
        status = await Message(self.channel,
                               I2C_commands["R_7B_MULTI"],
                               bytearray([0, 0, 0, address])).send(self.sca)
        self._check_i2c_status(status)
        rx_data = bytearray()
        for i in range(min([bytecount // 4 + 1, 4])):
            rx_data += await self._read_block(3-i)
        return rx_data[:bytecount]

    async def scan(self):
        """
        Scan all the addresses on the I2C bus of the SCA

        Returns:
            addresses (list): a list of the addresses that where found on the
            bus

        Raises:
            GBT_SCA_I2C_Exception: If there is an error that is not the
            (no-ack) error then it will be passed to the caller
        """
        scan_results = {}
        for address in range(127):
            try:
                _ = await self.read_byte(address)
            except GBT_SCA_I2C_Exception as e:
                scan_results[address] = e.code
            else:
                scan_results[address] = "OK"
        return scan_results
