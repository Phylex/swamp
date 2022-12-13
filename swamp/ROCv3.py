import pandas as pd
import logging

from hgcal_utilities import dict_utils


def count_bits(number):
    """
    Counts the number of '1' bits in the binary
    representation of the given integer

    :param number: Number to count the '1' bits of
    :type number: int
    :return: Number of bits that are '1'
    :rtype: int
    """
    bits = 0
    shifted_number = number
    while shifted_number > 0:
        bits += shifted_number & 1
        shifted_number = shifted_number >> 1
    return bits


def get_mask_min_bit(mask):
    """
    Calculate the position of the Lowest order bit that
    is '1'

    :param mask: Mask of which the position of the lowest order bit should
        be found in
    :type mask: int
    :return: Index (starting with 0) of the lowest order bit that is '1'
    :rtype: int
    """
    min_bit = 0
    while mask & 1 == 0:
        mask = mask >> 1
        min_bit += 1
    return min_bit


class ROCv3():
    """
    Responsible for handling all interaction with the ROCs. Effectively wraps
    the ROC hardware interface.
    """

    def __init__(
            self,
            transport,
            base_address,
            name,
            reset_pin,
            path_to_file):
        """
        Software counterpart of the HGCROCv3 ASIC to be used with the test
        systems

        :param transport: Object that encapsulates how to write and read to the
            physical chip
        :type transport: object
        :param base_address: Base address of the ROC to read and write to
        :type base_address: int
        :param name: Name of the ROC
        :type name: str
        :param reset_pin: i2c pin responsible for resetting the ROC
        :type reset_pin: object
        :param path_to_file: Path to the csv file containing the definition of
            the registers and parameters
        :type path_to_file: str
        """
        self.transaction_logger = logging.getLogger(f'{name}')
        self.transaction_logger.info(f'Initializing {name}'
                                     f' at base address {base_address}')
        self.validation_config = {}
        self.translation_dict = {}
        self.cache = {}
        self.name = name
        self.path_to_reg_definition = path_to_file
        self.base_address = base_address
        self.transport = transport
        self.reset_pin = reset_pin

        # Set ROC to reset during init
        self.reset_pin.write(0)

        # read in source of truth of the ROCv3 configuration
        config_table = pd.read_csv(path_to_file)

        # generate the translation table and the dict used to validate
        # user configurations
        sub_blocks = set(config_table['SubBlock'])
        for block in sub_blocks:
            self.validation_config[block] = {}
            self.translation_dict[block] = {}
            subtable = config_table[config_table['SubBlock'] == block]
            block_instances = set(subtable['BlockID'])
            for instance in block_instances:
                self.validation_config[block][instance] = {}
                self.translation_dict[block][instance] = {}
                instance_table = subtable[subtable['BlockID'] == instance]
                parameters = set(instance_table['parameter'])
                for parameter in parameters:
                    # build the validation dict
                    registers = instance_table[
                        instance_table['parameter'] == parameter]
                    bits = 0
                    for mask in registers['reg_mask']:
                        bits += count_bits(mask)
                    max_value = 2**bits - 1
                    self.validation_config[block][instance][parameter] = \
                        (0, max_value)
                    # build the translation dictionary
                    translator_data = {}
                    for r0, r1, reg_mask, param_mask, param_minbit in zip(
                            registers['R0'],
                            registers['R1'],
                            registers['reg_mask'],
                            registers['param_mask'],
                            registers['param_minbit']):
                        translator_data[(r0, r1)] = {
                            'param_mask': param_mask,
                            'reg_mask': reg_mask,
                            'param_minbit': param_minbit,
                            'reg_minbit': get_mask_min_bit(reg_mask)}
                    self.translation_dict[block][instance][parameter] = \
                        translator_data

        # generate the default state for the register cache
        for index, row in config_table.iterrows():
            self.cache[(row['R0'], row['R1'])] = row['defval_mask']

        # release the roc from reset
        self.reset_pin.write(1)
        self.transaction_logger.info("Initialization complete")

    def _validate(self, config: dict, reference: dict = None, read=False,
                  log_message_written=False):
        """
        Check if the configuration given in config only contains
        valid keys and values within the specified range

        :param config: The configuration that is to be checked (in the case of
            a recursive call, the relevant subsection is normally passed in)
        :type config: dict
        :param reference: The reference that the configuration is checked
            against, this is needed as the function is recursive and so needs
            to pass the correct section of the total reference configuration
            to the function call checking the sub-section, this parameter
            defaults to the full reference so the user should not specify it
        :type reference: dict
        :param read: Specifies if the configuration is for reading or writing
        :type read: bool, optional
        """
        if not log_message_written:
            self.transaction_logger.debug(
                "Validating configuration dictionary")

        if reference is None:
            reference = self.validation_config
        for key, val in config.items():
            if isinstance(reference[key], dict) and isinstance(val, dict)\
                    and key in reference:
                try:
                    self._validate(config[key], reference=reference[key],
                                   read=read, log_message_written=True)
                except KeyError as e:
                    message = e.args[0] + f" in {key}"
                    raise KeyError(message)
                except ValueError as e:
                    message = e.args[0] + f" in {key}"
                    raise ValueError(message)
            elif isinstance(val, int) and isinstance(reference[key], tuple):
                if val < reference[key][0] \
                        or val > reference[key][1]:
                    raise ValueError(f"{key} is {val} and outside of bounds "
                                     f"[{reference[key][0]},"
                                     f"{reference[key][1]}]")
            elif val is None and read:
                pass
            else:
                raise KeyError(f"invalid key {key}")
        return True

    def _translate_read(self, valid_config, translation_dictionary=None,
                        curr_key=[], param_reg_pairs=[],
                        written_log_message=False):
        if not written_log_message:
            self.transaction_logger.debug('Translating Read Config')
        if translation_dictionary is None:
            translation_dictionary = self.translation_dict
        for key, val in valid_config.items():
            if isinstance(val, dict):
                level_down_key = curr_key.copy()
                level_down_key.append(key)
                self._translate_read(
                    val,
                    translation_dictionary[key],
                    curr_key=level_down_key,
                    param_reg_pairs=param_reg_pairs,
                    written_log_message=True)
            else:
                new_key = curr_key.copy()
                new_key.append(key)
                registers = []
                param_registers = translation_dictionary[key].keys()
                masks = translation_dictionary[key].values()
                for r, m in zip(param_registers, masks):
                    registers.append(
                        (r[0], r[1],
                         m['param_minbit'],
                         m['reg_minbit'],
                         m['reg_mask'])
                    )
                param_reg_pairs.append((new_key, registers))
        return param_reg_pairs

    def read(self, configuration, from_hardware):
        """
        Reads register values from cache

        :param configuration: Configuration containing parameters to read
        :type configuration: dict
        :param from_hardware: Set to skip cache and read directly
            from registers
        :type from_hardware: bool
        :return: The values of parameters read from cache
        :rtype: dict
        """
        try:
            self._validate(configuration, read=True)
        except KeyError as err:
            raise KeyError(str(err.args[0]) + f" in ROC {self.name}")
        except ValueError as err:
            raise ValueError(str(err.args[0]) + f" in ROC {self.name}")
        parameters_to_be_read = self._translate_read(configuration,
                                                     param_reg_pairs=[])
        parameters = []
        self.transaction_logger.info(f'Reading {len(parameters_to_be_read)} '
                                     'parameters')
        if from_hardware is True:
            self.transaction_logger.info("Reading directly from registers")
        # read the values from the registers
        for param, reglist in parameters_to_be_read:
            parameter_value = 0
            for reg in reglist:
                param_minbit = reg[2]
                reg_minbit = reg[3]
                reg_mask = reg[4]
                if from_hardware is True:
                    self.transport.write(self.base_address, reg[0])
                    self.transport.write(self.base_address + 1, reg[1])
                    read_content = self.transport.read(
                        self.base_address + 2, 1)
                    self.cache[(reg[0], reg[1])] = read_content
                else:
                    read_content = self.cache[(reg[0], reg[1])]

                read_content = ((
                    read_content & reg_mask) >> reg_minbit) << param_minbit
                parameter_value = parameter_value | read_content
            parameters.append((param, parameter_value))

        # build the dict
        result = {}
        for keylist, value in parameters:
            subdict = dict_utils.nested_dict_from_keylist(keylist, value)
            dict_utils.update_dict(result, subdict, in_place=True)
        if from_hardware is True:
            self.transaction_logger.info(f'{len(parameters_to_be_read)} '
                                         'parameters read from registers')
        else:
            self.transaction_logger.info(f'{len(parameters_to_be_read)} '
                                         'parameters read from cache')
        return result

    def _translate(self, valid_config: dict,
                   translation_dictionary=None,
                   first_call=True) -> list:
        # do this to avoid weird referencing and static variable behaviour
        output_regs = []
        if first_call:
            self.transaction_logger.debug(
                "Translating configuration dictionary")

        if translation_dictionary is None:
            translation_dictionary = self.translation_dict
        for key, val in valid_config.items():
            if isinstance(val, dict):
                output_regs += self._translate(
                    val,
                    translation_dictionary[key],
                    first_call=False)
            else:
                param_registers = translation_dictionary[key].keys()
                masks = translation_dictionary[key].values()
                for r, m in zip(param_registers, masks):
                    aligned_val = \
                        ((val >> m['reg_minbit']) & m['param_mask'])\
                        << m['reg_minbit']
                    output_regs.append(
                        (r[0], r[1], aligned_val, m['reg_mask']))
        return output_regs

    def _cache(self, changed_registers: list) -> list:
        write_registers = []
        for reg in changed_registers:
            key = (reg[0], reg[1])
            aligned_val = reg[2]
            reg_mask = reg[3]
            self.transaction_logger.debug(f'Caching register {key}')
            cached_val = self.cache[key]
            new_val = (cached_val & (~reg_mask)) | aligned_val
            if new_val != cached_val:
                self.transaction_logger.debug("Cache miss")
                write_registers.append((reg[0], reg[1], new_val))
                self.cache[key] = new_val
            else:
                self.transaction_logger.debug("Cache hit")
        return write_registers

    def configure(self, configuration: dict, readback=False):
        """
        Writes to ROC registers

        :param configuration: Configuration containing values to write
        :type configuration: dict
        :param readback: Specifies whether to check written registers
            against cache. Defaults to False
        :type readback: bool, optional
        """
        try:
            self._validate(configuration)
        except KeyError as err:
            raise KeyError(str(err.args[0]) + f" in ROC {self.name}")
        except ValueError as err:
            raise ValueError(str(err.args[0]) + f" in ROC {self.name}")
        register_updates = self._translate(configuration)
        register_writes = self._cache(register_updates)
        self.transaction_logger.info("Updating configuration in "
                                     f'{len(register_writes)} registers')
        for reg in register_writes:
            try:
                self.transport.write(self.base_address, reg[0])
                self.transport.write(self.base_address + 1, reg[1])
                self.transport.write(self.base_address + 2, reg[2])
                if readback:
                    self.transport.write(self.base_address, reg[0])
                    self.transport.write(self.base_address + 1, reg[1])
                    rback_val = self.transport.read(self.base_address + 2, 1)
                    if rback_val != reg[2]:
                        raise IOError(
                            f'Read back {rback_val} from {(reg[0], reg[1])} '
                            f'does not match written value {reg[2]}')
            except IOError as err:
                raise IOError(
                    str(err.args[0]) +
                    f" during write operation to {self.name}")
        self.transaction_logger.info('Configuration written to '
                                     f'{len(register_writes)} registers')

    def reset_cache(self):
        # read in source of truth of the ROCv3 configuration
        config_table = pd.read_csv(self.path_to_reg_definition)
        for index, row in config_table.iterrows():
            self.cache[(row['R0'], row['R1'])] = row['defval_mask']

    def reset(self):
        self.reset_pin.write(0)
        self.reset_cache()
        self.reset_pin.write(1)

    def describe(self, _validation_config: dict = None):
        """
        Read the parameter description from the ROC register map

        :return: The ROC description with min and max parameter values
        :rtype: dict
        """
        roc_dict = {}
        if _validation_config is None:
            _validation_config = self.validation_config
        for key, value in _validation_config.items():
            if isinstance(value, dict):
                roc_dict[key] = self.describe(value)
            elif isinstance(value, tuple):
                roc_dict[key] = {'min': value[0],
                                 'max': value[1]}

        return roc_dict
