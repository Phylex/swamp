from smbus2 import SMBus
import logging
import gpiod
from typing import Union
from warnings import warn


class Xil_i2c():
    """
    i2c bus, effectively a fancy wrapper around the SMBus2 module
    that adds logging and a unified interface used across other
    forms of transport
    """

    def __init__(self, bus_id):
        """
        Store the bus id and initialize the smbus.

        :param bus_id: Bus id to start the SMBus module with, occupies the
            hardware by opening the corresponding file
        """
        self.bus_id = bus_id
        self.bus = SMBus()
        self.bus.open(self.bus_id)
        self.transaction_logger = logging.getLogger(f'Xil_i2c_bus_{bus_id}')
        self.transaction_logger.info("Initializing bus")

    def write(self, address, data: Union[int, bytearray]):
        """
        Write data to the i2c peripheral specified by the address

        :param address: The address of the peripheral on the bus to write
            data to, must be 0-127
        :type address: byte
        :param data: The data to be sent to the peripheral. If an `int` is
            passed a single transaction is perfomed, if a `bytearray` is
            passed then the entire data is written as a single i2c transaction
            (aka frames)
        :type data: int, bytearray
        """
        if isinstance(data, int):
            self.transaction_logger.debug(f'Write SingleByte addr = {address}'
                                          f' data = {hex(data)}')
            try:
                self.bus.write_byte(address, data)
            except IOError as e:
                self.transaction_logger.error("Error occurred during write: ",
                                              exc_info=True)
                raise IOError(e.args[0])
        else:
            if len(data) > 16:
                warn("large bulk i2c transactions are discouraged")
            printable_data = [hex(d) for d in data]
            self.transaction_logger.debug(f'Write MultiByte addr = {address}'
                                          f' data = {printable_data}')
            try:
                self.bus.write_i2c_block_data(address, 0, data)
            except IOError as e:
                self.transaction_logger.error("Error occurred during write: ",
                                              exc_info=True)
                raise IOError(e.args[0])

    def read(self, address: int, count: int = 1):
        """
        Read data from the i2c address specified

        :param address: The address of the peripheral on the bus to read data
            from, must be 0-127
        :type address: byte
        :param count: The number of bytes to read form the bus if the count is
            larger than one a block read is performed. Defaults to 1.
        :type count: int, optional
        :return: Array of values read for the different bytes as list of ints
        :rtype: list
        """
        if count == 1:
            self.transaction_logger.debug(f'Reading SingleByte '
                                          f'from addr = {address}')
            try:
                ret = self.bus.read_byte(address)
            except IOError as e:
                self.transaction_logger.error("Error occurred during read: ",
                                              exc_info=True)
                raise IOError(e.args[0])
            self.transaction_logger.debug(f'Read returned {ret}')
        else:
            self.transaction_logger.debug(f'Reading {count} Bytes '
                                          f'from addr = {address}')
            try:
                ret = self.bus.read_i2c_block_data(address, 0, count)
            except IOError as e:
                self.transaction_logger.error("Error occurred during read: ",
                                              exc_info=True)
                raise IOError(e.args[0])
            printable_data = [hex(d) for d in ret]
            self.transaction_logger.debug(f'Read returned {printable_data}')
        return ret

    def __del__(self):
        self.transaction_logger.info("Closing bus")
        self.bus.close()

    def scan(self):
        """
        Attempt to read from every address on the bus and collect all responses
        that are given to the read

        :return: A list of addresses that responded to the read attempt
        :rtype: list
        """
        scan_responses = []
        self.transaction_logger.info('Performing bus scan')
        for addr in range(128):
            try:
                self.bus.read_byte(addr)
            except OSError:
                pass
            else:
                scan_responses.append(addr)
        self.transaction_logger.info(
            f'Scan got responses from: {scan_responses}')
        return scan_responses


class Xil_gpio():
    """
    Object that controlls access to a GPIO pin of the hardware using the Kernel
    to actually manipulate the hardware
    """

    def __init__(self, chip, pin, mode):
        """
        open the File associated to the GPIO pin in user space and set the
        mode.

        :param chip: The name of the GPIO driver that the pin is connected to
        :type chip: str
        :param pin: The name of the Pin that should be driven. The name is
            registered in the Device tree that linux uses at boot
        :type pin: str
        :param mode: Either ``input`` or ``output``, determines the direction
            of the GPIO. When ``input`` is set the write action raises an
            Error. The mode pesists over the lifetime of the object
        :type mode: str
        """
        self._chip = gpiod.chip(chip)
        self._pin = self._chip.find_line(pin)
        config = gpiod.line_request()
        if mode == 'input':
            config.consumer = "xil_gpio_read"
            config.request_type = gpiod.line_request.DIRECTION_INPUT
        elif mode == 'output':
            config.consumer = "xil_gpio_write"
            config.request_type = gpiod.line_request.DIRECTION_OUTPUT
        else:
            raise ValueError(
                    "the gpio 'mode' needs to be either 'input' or 'output'")
        self._pin.request(config)
        self.mode = mode
        self.transaction_logger = logging.getLogger(f'pin_{pin}')
        self.transaction_logger.info("Pin initialized")

    def __del__(self):
        self.transaction_logger.info("Releasing pin")
        self._pin.release()

    def write(self, val):
        """
        Set the pin, only works in 'output' mode. Raises a ValueError otherwise

        :param val: Either ``0`` to set the pin to logic *LOW* or ``1`` to set
            the pin to logic *HIGH*
        :type val: int
        """
        self.transaction_logger.debug(f'Writing pin to {val}')
        if val not in [0, 1]:
            raise ValueError(
                    'A gpio can only be set "HIGH" => 1, or "LOW" => 0')
        if self.mode != 'output':
            raise ValueError(
                    'To set the output of the pin it needs to '
                    'be set as "output"')
        self._pin.set_value(val)
        self.transaction_logger.debug(f'Pin written to {val}')

    def read(self):
        """
        Read from the gpio pin

        :return: 0 if the pin is logical LOW and 1 if the pin is set/pulled
            to HIGH
        :rtype: int
        """
        self.transaction_logger.debug("Reading pin")
        pin_value = self._pin.get_value()
        self.transaction_logger.debug(f"Pin value read: {pin_value}")
        return pin_value
