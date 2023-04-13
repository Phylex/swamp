=====
SWAMP
=====


.. image:: https://img.shields.io/pypi/v/swamp.svg
        :target: https://pypi.python.org/pypi/swamp

.. image:: https://img.shields.io/travis/phylex/swamp.svg
        :target: https://travis-ci.com/phylex/swamp

.. image:: https://readthedocs.org/projects/swamp/badge/?version=latest
        :target: https://swamp.docs.cern.ch/en/latest/?version=latest
        :alt: Documentation Status


The SoftWare Architectural Mirroring Platform for the HGCAL Detector


* Free software: MIT license
* Documentation: https://swamp.docs.cern.ch.


Overview
--------
The SoftWare Architectural Mirroring Platform for the HGCAL Detector is software that is designed to handle
the detector configuration and the configuration of component parts throughout the assembly and testing phase.

It is made of a composable set of objects, each representing an ASIC in the hardware. The topology of the connected
objects mirrors that of the hardware. The Software controls the hardware configuration via the slow-control channel.
It uses the Transactor (FPGA) Firmware to connect to the hardware.

Features
--------
* Easy to usa API, you do not need to be an ASIC or embedded software expert to configure your detector!
* Detailed logs and robust error handling: Something went wrong? No need to sort throug undocumented scripts written a year ago to find the one bit that needs changing.
  SWAMP validates you config and your command befor sending them, telling you if there was any illegal configuration!
  In case of a system fault, the error message provides and logs provide detailed information so that you can find the error quickly and frustration free!
* Extensible: Got a new ASIC to integrate? Only write a single class and let SWAMP handle the rest.
* Virtual hardware: Test your setup without the hardware, thanks to software emulation of!
* Ready to go: SWAMP will be deployed as pypi package for quick and easy integration

---

Credits
-------
This package was Originaly authored by Alexander Becker with lots of additional help by Armando Bermudez Martinez and firmware support by Martim Rosado.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
