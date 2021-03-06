#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2020, Emmanuel Blot <emmanuel.blot@free.fr>
# All rights reserved.

#pylint: disable-msg=empty-docstring
#pylint: disable-msg=missing-docstring
#pylint: disable-msg=no-self-use

import logging
from collections import defaultdict
from contextlib import redirect_stdout
from doctest import testmod
from io import StringIO
from os import environ
from string import ascii_letters
from sys import modules, stdout, version_info
from unittest import TestCase, TestSuite, makeSuite, main as ut_main
from urllib.parse import urlsplit
from pyftdi import FtdiLogger
from pyftdi.ftdi import Ftdi, FtdiMpsseError
from pyftdi.gpio import GpioController
from pyftdi.serialext import serial_for_url
from pyftdi.usbtools import UsbTools
from backend.loader import MockLoader

# need support for f-string syntax
if version_info[:2] < (3, 6):
    raise AssertionError('Python 3.6 is required for this module')


class MockUsbToolsTestCase(TestCase):
    """Test UsbTools APIs.
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ftmany.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Enumerate FTDI devices."""
        ftdis = [(0x403, pid)
                 for pid in (0x6001, 0x6010, 0x6011, 0x6014, 0x6015)]
        count = len(UsbTools.find_all(ftdis))
        self.assertEqual(count, 6)

    def test_device(self):
        """Access and release FTDI device."""
        ftdis = [(0x403, 0x6001)]
        ft232rs = UsbTools.find_all(ftdis)
        self.assertEqual(len(ft232rs), 1)
        devdesc, ifcount = ft232rs[0]
        self.assertEqual(ifcount, 1)
        dev = UsbTools.get_device(devdesc)
        self.assertIsNotNone(dev)
        UsbTools.release_device(dev)

    def test_string(self):
        """Retrieve a string from its identifier."""
        ftdis = [(0x403, 0x6010)]
        ft2232h = UsbTools.find_all(ftdis)[0]
        devdesc, _ = ft2232h
        dev = UsbTools.get_device(devdesc)
        serialn = UsbTools.get_string(dev, dev.iSerialNumber)
        self.assertEqual(serialn, 'FT2DEF')

    def test_list_devices(self):
        """List FTDI devices."""
        vid = 0x403
        vids = {'ftdi': vid}
        pids = {
            vid: {
                '230x': 0x6015,
                '232r': 0x6001,
                '232h': 0x6014,
                '2232h': 0x6010,
                '4232h': 0x6011,
            }
        }
        devs = UsbTools.list_devices('ftdi:///?', vids, pids, vid)
        self.assertEqual(len(devs), 6)
        ifmap = {
            0x6001: 1,
            0x6010: 2,
            0x6011: 4,
            0x6014: 1,
            0x6015: 1
        }
        for dev, desc in devs:
            strings = UsbTools.build_dev_strings('ftdi', vids, pids,
                                                 [(dev, desc)])
            self.assertEqual(len(strings), ifmap[dev.pid])
            for url, _ in strings:
                parts, _ = UsbTools.parse_url(url, 'ftdi', vids, pids, vid)
                self.assertEqual(parts.vid, dev.vid)
                self.assertEqual(parts.pid, dev.pid)
                self.assertEqual(parts.bus, dev.bus)
                self.assertEqual(parts.address, dev.address)
                self.assertEqual(parts.sn, dev.sn)
        devs = UsbTools.list_devices('ftdi://:232h/?', vids, pids, vid)
        self.assertEqual(len(devs), 2)
        devs = UsbTools.list_devices('ftdi://:2232h/?', vids, pids, vid)
        self.assertEqual(len(devs), 1)


class MockFtdiDiscoveryTestCase(TestCase):
    """Test FTDI device discovery APIs.
       These APIs are FTDI wrappers for UsbTools APIs.
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ftmany.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_list_devices(self):
        """List FTDI devices."""
        devs = Ftdi.list_devices('ftdi:///?')
        self.assertEqual(len(devs), 6)
        devs = Ftdi.list_devices('ftdi://:232h/?')
        self.assertEqual(len(devs), 2)
        devs = Ftdi.list_devices('ftdi://:2232h/?')
        self.assertEqual(len(devs), 1)
        devs = Ftdi.list_devices('ftdi://:4232h/?')
        self.assertEqual(len(devs), 1)
        out = StringIO()
        Ftdi.show_devices('ftdi:///?', out)
        lines = [l.strip() for l in out.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 10)
        portmap = defaultdict(int)
        reference = {'232': 1, '2232': 2, '4232': 4, '232h': 2, '230x': 1}
        for line in lines:
            url = line.split(' ')[0].strip()
            parts = urlsplit(url)
            self.assertEqual(parts.scheme, 'ftdi')
            self.assertRegex(parts.path, r'^/[1-4]$')
            product = parts.netloc.split(':')[1]
            portmap[product] += 1
        self.assertEqual(portmap, reference)


class MockSimpleDeviceTestCase(TestCase):
    """Test FTDI APIs with a single-port FTDI device (FT232H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Check simple enumeration of a single FTDI device."""
        ftdi = Ftdi()
        temp_stdout = StringIO()
        with redirect_stdout(temp_stdout):
            self.assertRaises(SystemExit, ftdi.open_from_url, 'ftdi:///?')
        lines = [l.strip() for l in temp_stdout.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('ftdi://'))
        # skip description, i.e. consider URL only
        self.assertTrue(lines[0].split(' ')[0].endswith('/1'))


class MockDualDeviceTestCase(TestCase):
    """Test FTDI APIs with two similar single-port FTDI devices (FT232H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft232h_x2.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Check simple enumeration of a 2-port FTDI device."""
        ftdi = Ftdi()
        temp_stdout = StringIO()
        with redirect_stdout(temp_stdout):
            self.assertRaises(SystemExit, ftdi.open_from_url, 'ftdi:///?')
        lines = [l.strip() for l in temp_stdout.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.startswith('ftdi://'))
            # skip description, i.e. consider URL only
            self.assertTrue(line.split(' ')[0].endswith('/1'))


class MockTwoPortDeviceTestCase(TestCase):
    """Test FTDI APIs with a dual-port FTDI device (FT2232H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft2232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Check simple enumeration of a 4-port FTDI device."""
        ftdi = Ftdi()
        temp_stdout = StringIO()
        with redirect_stdout(temp_stdout):
            self.assertRaises(SystemExit, ftdi.open_from_url, 'ftdi:///?')
        lines = [l.strip() for l in temp_stdout.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 2)
        for pos, line in enumerate(lines, start=1):
            self.assertTrue(line.startswith('ftdi://'))
            # skip description, i.e. consider URL only
            self.assertTrue(line.split(' ')[0].endswith(f'/{pos}'))


class MockFourPortDeviceTestCase(TestCase):
    """Test FTDI APIs with a quad-port FTDI device (FT4232H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft4232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Check simple enumeration of two similar FTDI device."""
        ftdi = Ftdi()
        temp_stdout = StringIO()
        with redirect_stdout(temp_stdout):
            self.assertRaises(SystemExit, ftdi.open_from_url, 'ftdi:///?')
        lines = [l.strip() for l in temp_stdout.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 4)
        for pos, line in enumerate(lines, start=1):
            self.assertTrue(line.startswith('ftdi://'))
            # skip description, i.e. consider URL only
            self.assertTrue(line.split(' ')[0].endswith(f'/{pos}'))


class MockManyDevicesTestCase(TestCase):
    """Test FTDI APIs with several, mixed type FTDI devices
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ftmany.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_enumerate(self):
        """Check simple enumeration of two similar FTDI device."""
        ftdi = Ftdi()
        temp_stdout = StringIO()
        with redirect_stdout(temp_stdout):
            self.assertRaises(SystemExit, ftdi.open_from_url, 'ftdi:///?')
        lines = [l.strip() for l in temp_stdout.getvalue().split('\n')]
        lines.pop(0)  # "Available interfaces"
        while lines and not lines[-1]:
            lines.pop()
        self.assertEqual(len(lines), 10)
        for line in lines:
            self.assertTrue(line.startswith('ftdi://'))
            # skip description, i.e. consider URL only
            url = line.split(' ')[0]
            urlparts = urlsplit(url)
            self.assertEqual(urlparts.scheme, 'ftdi')
            parts = urlparts.netloc.split(':')
            if parts[1] == '4232':
                # def file contains no serial number, so expect bus:addr syntax
                self.assertEqual(len(parts), 4)
                self.assertRegex(parts[2], r'^\d$')
                self.assertRegex(parts[3], r'^\d$')
            else:
                # other devices are assigned a serial number
                self.assertEqual(len(parts), 3)
                self.assertTrue(parts[2].startswith('FT'))
            self.assertRegex(urlparts.path, r'^/\d$')


class MockSimpleDirectTestCase(TestCase):
    """Test FTDI open/close APIs with a basic featured FTDI device (FT230H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft230x.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_open_close(self):
        """Check simple open/close sequence."""
        ftdi = Ftdi()
        ftdi.open_from_url('ftdi:///1')
        self.assertEqual(ftdi.usb_path, (1, 1, 0))
        ftdi.close()

    def test_open_bitbang(self):
        """Check simple open/close BitBang sequence."""
        ftdi = Ftdi()
        ftdi.open_bitbang_from_url('ftdi:///1')
        ftdi.close()

    def test_open_mpsse(self):
        """Check simple MPSSE access."""
        ftdi = Ftdi()
        # FT230X is a pure UART bridge, MPSSE should not be available
        self.assertRaises(FtdiMpsseError,
                          ftdi.open_mpsse_from_url, 'ftdi:///1')


class MockSimpleMpsseTestCase(TestCase):
    """Test FTDI open/close APIs with a MPSSE featured FTDI device (FT232H)
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test_open_close(self):
        """Check simple open/close sequence."""
        ftdi = Ftdi()
        ftdi.open_from_url('ftdi:///1')
        self.assertEqual(ftdi.usb_path, (4, 5, 0))
        ftdi.close()

    def test_open_bitbang(self):
        """Check simple open/close BitBang sequence."""
        ftdi = Ftdi()
        ftdi.open_bitbang_from_url('ftdi:///1')
        ftdi.close()

    def test_open_mpsse(self):
        """Check simple MPSSE access."""
        ftdi = Ftdi()
        ftdi.open_mpsse_from_url('ftdi:///1')
        ftdi.close()


class MockSimpleGpioTestCase(TestCase):
    """Test FTDI GPIO APIs
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test(self):
        """Check simple GPIO write and read sequence."""
        gpio = GpioController()
        # access to the virtual GPIO port
        out_pins = 0xAA
        gpio.configure('ftdi://:232h/1', direction=out_pins)
        bus, address, iface = gpio.ftdi.usb_path
        self.assertEqual((bus, address, iface), (4, 5, 0))
        vftdi = self.loader.get_virtual_ftdi(bus, address)
        gpio.write_port(0xF3)
        self.assertEqual(vftdi.gpio, 0xAA & 0xF3)
        vftdi.gpio = 0x0c
        vio = gpio.read_port()
        self.assertEqual(vio, (0xAA & 0xF3) | (~0xAA & 0x0c))
        gpio.close()


class MockSimpleUartTestCase(TestCase):
    """Test FTDI UART APIs
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = MockLoader()
        with open('pyftdi/tests/resources/ft232h.yaml', 'rb') as yfp:
            cls.loader.load(yfp)
        UsbTools.flush_cache()

    @classmethod
    def tearDownClass(cls):
        cls.loader.unload()

    def test(self):
        """Check simple TX/RX sequence."""
        port = serial_for_url('ftdi:///1')
        bus, address, _ = port.usb_path
        vftdi = self.loader.get_virtual_ftdi(bus, address)
        msg = ascii_letters
        port.write(msg.encode())
        buf = vftdi.uart_read(len(ascii_letters)+10).decode()
        self.assertEqual(msg, buf)
        msg = ''.join(reversed(msg))
        vftdi.uart_write(msg.encode())
        buf = port.read(len(ascii_letters)).decode()
        self.assertEqual(msg, buf)
        port.close()


def suite():
    suite_ = TestSuite()
    suite_.addTest(makeSuite(MockUsbToolsTestCase, 'test'))
    suite_.addTest(makeSuite(MockFtdiDiscoveryTestCase, 'test'))
    suite_.addTest(makeSuite(MockSimpleDeviceTestCase, 'test'))
    suite_.addTest(makeSuite(MockDualDeviceTestCase, 'test'))
    suite_.addTest(makeSuite(MockTwoPortDeviceTestCase, 'test'))
    suite_.addTest(makeSuite(MockFourPortDeviceTestCase, 'test'))
    suite_.addTest(makeSuite(MockManyDevicesTestCase, 'test'))
    suite_.addTest(makeSuite(MockSimpleDirectTestCase, 'test'))
    suite_.addTest(makeSuite(MockSimpleMpsseTestCase, 'test'))
    suite_.addTest(makeSuite(MockSimpleGpioTestCase, 'test'))
    suite_.addTest(makeSuite(MockSimpleUartTestCase, 'test'))
    return suite_


def main():
    testmod(modules[__name__])
    FtdiLogger.log.addHandler(logging.StreamHandler(stdout))
    level = environ.get('FTDI_LOGLEVEL', 'warning').upper()
    try:
        loglevel = getattr(logging, level)
    except AttributeError:
        raise ValueError(f'Invalid log level: {level}')
    FtdiLogger.set_level(loglevel)
    # Force PyUSB to use PyFtdi test framework for USB backends
    UsbTools.BACKENDS = ('backend.usbmock', )
    ut_main(defaultTest='suite')


if __name__ == '__main__':
    main()
