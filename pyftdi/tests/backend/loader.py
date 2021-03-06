"""Virtual USB backend loader.
"""

# Copyright (c) 2020, Emmanuel Blot <emmanuel.blot@free.fr>
# All rights reserved.

#pylint: disable-msg=missing-docstring
#pylint: disable-msg=too-few-public-methods
#pylint: disable-msg=too-many-branches
#pylint: disable-msg=no-self-use

from logging import getLogger
from sys import version_info
from typing import BinaryIO
from ruamel.yaml import load_all as yaml_load
from ruamel.yaml.loader import Loader
from pyftdi.misc import to_bool
from .usbmock import (MockConfiguration, MockDevice, MockInterface,
                      MockEndpoint, get_backend)
from .consts import USBCONST

# need support for f-string syntax
if version_info[:2] < (3, 6):
    raise AssertionError('Python 3.6 is required for this module')


class MockLoader:
    """Load a virtual USB bus environment from a YaML description stream.
    """

    def __init__(self):
        self.log = getLogger('pyftdi.mock.backend')
        self._last_ep_idx = 0

    def load(self, yamlfp: BinaryIO) -> None:
        """Load a YaML configuration stream.

           :param yamlfp: YaML stream to be parsed
        """
        backend = get_backend()
        with yamlfp:
            ydefs = yaml_load(yamlfp, Loader=Loader)
            try:
                for ydef in ydefs:
                    self._build_root(backend, ydef)
            except Exception as exc:
                raise ValueError(f'Invalid configuration: {exc}')
        self._validate()

    def unload(self):
        backend = get_backend()
        backend.flush_devices()

    def get_virtual_ftdi(self, bus, address):
        return get_backend().get_virtual_ftdi(bus, address)

    def _validate(self):
        locations = set()
        for device in get_backend().devices:
            # check location on buses
            location = (device.bus, device.address)
            if location in locations:
                raise ValueError('Two devices on same USB location '
                                 f'{location}')
            locations.add(location)
            configs = set()
            ifaces = set()
            epaddrs = set()
            for config in device.configurations:
                cfgval = config.bConfigurationValue
                if cfgval in configs:
                    raise ValueError(f'Config {cfgval} assigned twice')
                configs.add(cfgval)
                for iface in config.interfaces:
                    ifval = iface.bInterfaceNumber
                    if ifval in ifaces:
                        raise ValueError(f'Interface {ifval} assigned twice')
                    ifaces.add(iface)
                    # check endpoint addresses
                    for endpoint in iface.endpoints:
                        epaddr = endpoint.bEndpointAddress
                        if epaddr in epaddrs:
                            raise ValueError(f'EP 0x{epaddr:02x} '
                                             'assigned twice')
                        epaddrs.add(epaddr)

    def _build_root(self, backend, container):
        backend.flush_devices()
        if not isinstance(container, dict):
            raise ValueError('Top-level not a dict')
        for ykey, yval in container.items():
            if ykey != 'devices':
                continue
            if not isinstance(yval, list):
                raise ValueError('Devices not a list')
            for yitem in yval:
                if not isinstance(container, dict):
                    raise ValueError('Device not a dict')
                self._last_ep_idx = 0
                device = self._build_device(yitem)
                device.build()
                backend.add_device(device)

    def _build_device(self, container):
        devdesc = None
        configs = []
        properties = {}
        for ykey, yval in container.items():
            if ykey == 'descriptor':
                if not isinstance(yval, dict):
                    raise ValueError('Device descriptor not a dict')
                devdesc = self._build_device_descriptor(yval)
                continue
            if ykey == 'configurations':
                if not isinstance(yval, list):
                    raise ValueError('Configurations not a list')
                configs = [self._build_configuration(conf) for conf in yval]
                continue
            if ykey == 'noaccess':
                yval = to_bool(yval)
            if ykey == 'speed' and isinstance(yval, str):
                try:
                    yval = USBCONST.speeds[yval]
                except KeyError:
                    raise ValueError(f'Invalid device speed {yval}')
            properties[ykey] = yval
        if not devdesc:
            raise ValueError('Missing device descriptor')
        if not configs:
            configs = [self._build_configuration({})]
        device = MockDevice(devdesc, **properties)
        for config in configs:
            device.add_configuration(config)
        return device

    def _build_device_descriptor(self, container) -> dict:
        kmap = {
            'usb': 'bcdUSB',
            'class': 'bDeviceClass',
            'subclass': 'bDeviceSubClass',
            'protocol': 'bDeviceProtocol',
            'maxpacketsize': 'bMaxPacketSize0',
            'vid': 'idVendor',
            'pid': 'idProduct',
            'version': 'bcdDevice',
            'manufacturer': 'iManufacturer',
            'product': 'iProduct',
            'serialnumber': 'iSerialNumber',
        }
        kwargs = {}
        for ckey, cval in container.items():
            try:
                dkey = kmap[ckey]
            except KeyError:
                raise ValueError(f'Unknown descriptor field {dkey}')
            kwargs[dkey] = cval
        return kwargs

    def _build_configuration(self, container):
        if not isinstance(container, dict):
            raise ValueError('Invalid configuration entry')
        cfgdesc = {}
        interfaces = []
        for ykey, yval in container.items():
            if ykey == 'descriptor':
                if not isinstance(yval, dict):
                    raise ValueError('Configuration descriptor not a dict')
                cfgdesc = self._build_config_descriptor(yval)
                continue
            if ykey == 'interfaces':
                if not isinstance(yval, list):
                    raise ValueError('Interfaces not a list')
                for conf in yval:
                    interfaces.extend(self._build_interfaces(conf))
                continue
            raise ValueError(f'Unknown config entry {ykey}')
        if not interfaces:
            interfaces.extend(self._build_interfaces({}))
        config = MockConfiguration(cfgdesc)
        for iface in interfaces:
            config.add_interface(iface)
        return config

    def _build_config_descriptor(self, container) -> dict:
        kmap = {
            'attributes': 'bmAttributes',
            'maxpower': 'bMaxPower',
            'configuration': 'iConfiguration'
        }
        kwargs = {}
        for ckey, cval in container.items():
            try:
                dkey = kmap[ckey]
            except KeyError:
                raise ValueError(f'Unknown descriptor field {ckey}')
            if ckey == 'maxpower':
                cval //= 2
            elif ckey == 'attributes':
                if not isinstance(cval, list):
                    raise ValueError('Invalid config attributes')
                aval = 0x80
                for feature in cval:
                    if feature == 'selfpowered':
                        aval |= 1 << 6
                    if feature == 'wakeup':
                        aval |= 1 << 5
                cval = aval
            elif ckey == 'configuration':
                pass
            else:
                raise ValueError(f'Unknown config descriptor {ckey}')
            kwargs[dkey] = cval
        return kwargs

    def _build_interfaces(self, container):
        if not isinstance(container, dict):
            raise ValueError('Invalid interface entry')
        repeat = 1
        altdef = [{}]
        for ikey, ival in container.items():
            if ikey == 'alternatives':
                if not isinstance(ival, list):
                    raise ValueError(f'Invalid interface entry {ikey}')
                if len(ival) > 1:
                    raise ValueError('Unsupported alternative count')
                if ival:
                    altdef = ival
            elif ikey == 'repeat':
                if not isinstance(ival, int):
                    raise ValueError(f'Invalid repeat count {ival}')
                repeat = ival
            else:
                raise ValueError(f'Invalid interface entry {ikey}')
        ifaces = []
        while  repeat:
            repeat -= 1
            ifdesc, endpoints = self._build_alternative(altdef[0])
            self._last_ep_idx = max([ep.bEndpointAddress & 0x7F
                                     for ep in endpoints])
            iface = MockInterface(ifdesc)
            for endpoint in endpoints:
                iface.add_endpoint(endpoint)
            ifaces.append(iface)
        return ifaces

    def _build_alternative(self, container):
        if not isinstance(container, dict):
            raise ValueError('Invalid alternative entry')
        ifdesc = {}
        endpoints = []
        for ikey, ival in container.items():
            if ikey == 'descriptor':
                if not isinstance(ival, dict):
                    raise ValueError('Interface descriptor not a dict')
                ifdesc = self._build_interface_descriptor(ival)
                continue
            if ikey == 'endpoints':
                if not isinstance(ival, list):
                    raise ValueError('Interface encpoints not a list')
                endpoints = [self._build_endpoint(ep) for ep in ival]
        if not endpoints:
            epidx = self._last_ep_idx
            epidx += 1
            desc = {'descriptor': {'direction': 'in', 'number': epidx}}
            ep0 = self._build_endpoint(desc)
            epidx += 1
            desc = {'descriptor': {'direction': 'out', 'number': epidx}}
            ep1 = self._build_endpoint(desc)
            endpoints = [ep0, ep1]
        return ifdesc, endpoints

    def _build_interface_descriptor(self, container) -> dict:
        kmap = {
            'class': 'bDeviceClass',
            'subclass': 'bDeviceSubClass',
            'protocol': 'bDeviceProtocol',
            'interface': 'iInterface',
        }
        kwargs = {}
        for ckey, cval in container.items():
            try:
                dkey = kmap[ckey]
            except KeyError:
                raise ValueError(f'Unknown descriptor field {ckey}')
            kwargs[dkey] = cval
        return kwargs

    def _build_endpoint(self, container):
        if not isinstance(container, dict):
            raise ValueError('Invalid endpoint entry')
        epdesc = None
        for ikey, ival in container.items():
            if ikey == 'descriptor':
                if not isinstance(ival, dict):
                    raise ValueError('Interface descriptor not a dict')
                epdesc = self._build_endpoint_descriptor(ival)
                continue
            raise ValueError(f'Unknown config entry {ikey}')
        if not epdesc:
            raise ValueError('Missing endpoint descriptor')
        endpoint = MockEndpoint(epdesc)
        return endpoint

    def _build_endpoint_descriptor(self, container) -> dict:
        kwargs = {}
        if 'number' not in container:
            raise ValueError('Missing endpoint number')
        if 'direction' not in container:
            raise ValueError('Missing endpoint direction')
        if 'type' not in container:
            container = dict(container)
            container['type'] = 'bulk'
        for ekey, val in container.items():
            if ekey == 'maxpacketsize':
                kwargs['wMaxPacketSize'] = val
                continue
            if ekey == 'interval':
                kwargs['bInterval'] = val
                continue
            if ekey == 'direction':
                try:
                    value = USBCONST.endpoints[val.lower()]
                except KeyError:
                    raise ValueError('Unknown endpoint direction')
                kwargs.setdefault('bEndpointAddress', 0)
                kwargs['bEndpointAddress'] |= value
                continue
            if ekey == 'number':
                if not isinstance(val, int) or not 0 < val < 16:
                    raise ValueError(f'Invalid endpoint number {val}')
                kwargs.setdefault('bEndpointAddress', 0)
                kwargs['bEndpointAddress'] |= val
                continue
            if ekey == 'type':
                try:
                    kwargs['bmAttributes'] = \
                        USBCONST.endpoint_types[val.lower()]
                except KeyError:
                    raise ValueError('Unknown endpoint type')
                continue
            if ekey == 'endpoint':
                kwargs['iEndpoint'] = val
                continue
            raise ValueError(f'Unknown endpoint entry {ekey}')
        return kwargs
