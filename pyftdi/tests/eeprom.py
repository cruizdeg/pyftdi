#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018, Stephen Goadhouse <sgoadhouse@virginia.edu>
# Copyright (c) 2019, Emmanuel Blot <emmanuel.blot@free.fr>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the Neotion nor the names of its contributors may
#       be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL NEOTION BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import logging
import unittest
from doctest import testmod
from os import environ
from sys import modules, stdout
from pyftdi import FtdiLogger
from pyftdi.ftdi import Ftdi
from pyftdi.misc import hexdump, to_bool

#pylint: disable-msg=missing-docstring


class EepromTestCase(unittest.TestCase):
    """FTDI EEPROM access method test case"""

    @classmethod
    def setUpClass(cls):
        """Default values"""
        cls.eeprom_size = int(environ.get('FTDI_EEPROM_SIZE', '256'))
        cls.url = environ.get('FTDI_DEVICE', 'ftdi://ftdi:2232h/1')


    def setUp(self):
        """Open a connection to the FTDI, defining which pins are configured as
           output and input"""
        # out_pins value of 0x00 means all inputs
        out_pins = 0x00
        try:
            ftdi = Ftdi()
            # If you REALLY muck things up, need to use this open_bitbang()
            # function directly and enter vendor and product ID:
            # ftdi.open_bitbang(vendor=0x0403, product=0x6011,
            #                   direction=out_pins)
            ftdi.open_bitbang_from_url(self.url, direction=out_pins)
            self.ftdi = ftdi
        except IOError as ex:
            raise IOError('Unable to open USB port: %s' % str(ex))

    def tearDown(self):
        """Close the FTDI connection"""
        self.ftdi.close()

    def test_eeprom_read(self):
        """Simple test to demonstrate EEPROM read out.
        """
        ref_data = self.ftdi.read_eeprom(eeprom_size=self.eeprom_size)
        print(hexdump(ref_data))
        # check that the right number of bytes were read
        self.assertEqual(len(ref_data), self.eeprom_size)
        # Pull out actual checksum from EEPROM data
        ck_act = (ref_data[-1] << 8) | ref_data[-2]
        # compute expected checksum value over the EEPROM contents, except
        # the EEPROM word
        ck_expo = self.ftdi.calc_eeprom_checksum(ref_data[:-2])
        self.assertEqual(ck_act, ck_expo)
        maxsize = self.eeprom_size
        # verify access to various data segments
        segments = ((1, 2), (1, 3), (2, 4), (2, 5), (maxsize-8, 8),
                    (maxsize-3, 3), (0, maxsize))
        for start, size in segments:
            chunk = self.ftdi.read_eeprom(start, size, self.eeprom_size)
            self.assertEqual(len(chunk), size)
            self.assertEqual(chunk, ref_data[start:start+size])
        # verify reject access to various invalid data segments
        segments = (-1, 2), (0, maxsize+1), (maxsize-6, maxsize+1)
        for start, size in segments:
            self.assertRaises(ValueError, self.ftdi.read_eeprom, start, size)

    def test_eeprom_write_reject(self):
        """Simple test to demonstrate rejection of invalid EEPROM write
           requests.
        """
        ref_data = self.ftdi.read_eeprom(eeprom_size=self.eeprom_size)
        # check that the right number of bytes were read
        self.assertEqual(len(ref_data), self.eeprom_size)
        # verify reject access to various invalid data segments
        segments = (-1, 2), (0, 257), (250, 7)
        for start, size in segments:
            self.assertRaises(ValueError, self.ftdi.write_eeprom, start,
                              [0] * size, self.eeprom_size)

    def test_eeprom_write(self):
        """Simple test to demonstrate EEPROM write requests.
        """
        self.ftdi.write_eeprom(0x80, b'test', eeprom_size=self.eeprom_size)


def suite():
    suite_ = unittest.TestSuite()
    suite_.addTest(unittest.makeSuite(EepromTestCase, 'test'))
    return suite_


def main():
    if to_bool(environ.get('FTDI_DEBUG', 'off')):
        FtdiLogger.log.addHandler(logging.StreamHandler(stdout))
    level = environ.get('FTDI_LOGLEVEL', 'info').upper()
    try:
        loglevel = getattr(logging, level)
    except AttributeError:
        raise ValueError('Invalid log level: %s' %level)
    FtdiLogger.set_level(loglevel)
    testmod(modules[__name__])
    unittest.main(defaultTest='suite')


if __name__ == '__main__':
    main()