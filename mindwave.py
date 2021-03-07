#!/usr/bin/env python3

import select, threading
import struct

from time import time, sleep
import serial  # pip3 install pyserial
import os

from collections import namedtuple

# Byte codes
codes = dict(
    CONNECT=b'\xc0',
    DISCONNECT=b'\xc1',
    AUTOCONNECT=b'\xc2',
    SYNC=b'\xaa',
    EXCODE=b'\x55',
    POOR_SIGNAL=b'\x02',
    ATTENTION=b'\x04',
    MEDITATION=b'\x05',
    BLINK=b'\x16',
    HEADSET_CONNECTED=b'\xd0',
    HEADSET_NOT_FOUND=b'\xd1',
    HEADSET_DISCONNECTED=b'\xd2',
    REQUEST_DENIED=b'\xd3',
    STANDBY_SCAN=b'\xd4',
    RAW_VALUE=b'\x80',
    FREQS=b'\x83'
)

EEGPowerData = namedtuple('EEGPowerData', 'delta theta lowalpha highalpha lowbeta highbeta lowgamma midgamma')

# Status codes
STATUS_CONNECTED = b'connected'
STATUS_SCANNING = b'scanning'
STATUS_STANDBY = b'standby'

# code2com
code2name = {v:k for k,v in codes.items()}
ord2name = {ord(k): v for k, v in code2name.items()}


class Serial:
    def __init__(self, port, timeout=0):
        self.port = port
        self.timeout = timeout
        self.state = None

    def __enter__(self):  # context manager magic
        try:
            self.serial = serial.Serial(self.port, 57600, timeout=self.timeout)
        except serial.serialutil.SerialException as exc:
            print(exc)
            if exc.errno == 13:
                print(f'try to get permission with command like "sudo chmod a+rw {self.port}"')
                os._exit(1)
            elif exc.errno == 2:
                pnum = int(self.port[-1])
                if pnum == 9:
                    os._exit(1)
                else:
                    self.port = self.port[:-1] + str(pnum +1)
                    self.__enter__()
            else:        
                os._exit(1)
            
        return self

    def __exit__(self, *args):  # context manager magic
        self.serial.close()


class Device(Serial):
    def __init__(self, port):
        super().__init__(port)
        self.state = {'ATTENTION':0, 'MEDITATION':0, 'POOR_SIGNAL':0}
        self.dump_file = open(f'{int(time())}.freq', 'wb')

    def __exit__(self, *args):  # context manager magic
        self.serial.close()
        self.dump_file.close()

    def run(self):
        """Run the listener thread."""
        s = self.serial

        # Re-apply settings to ensure packet stream
        s.write(codes['DISCONNECT'])
        d = s.getSettingsDict()
        for i in range(2):
            d['rtscts'] = not d['rtscts']
            s.applySettingsDict(d)

        while True:
            # Begin listening for packets
            try:
                if s.read() == codes['SYNC'] and s.read() == codes['SYNC']:
                    # Packet found, determine plength
                    while True:
                        plength = s.read()
                        if not plength:
                            continue
                        if ord(plength) != 170:
                            break

                    if ord(plength) > 170:
                        continue


                    # Read in the payload
                    payload = s.read(ord(plength))

                    _chksum = s.read()

                    self.parse_payload(payload)

            except (select.error, OSError):
                break
            except serial.SerialException:
                s.close()
                break

    def parse_payload(self, payload):
        """Parse the payload to determine an action."""
        # print(f"payload = {payload}")
        #print('pipisque')
        while payload:
            # Parse data row
            excode = 0
            try:
                code, payload = payload[0], payload[1:]
                # print('code:', code_dict.get(code), ord_dict.get(code), code)
            except IndexError:
                pass

            scode = ord2name.get(code)

            while scode == 'EXCODE':
                # Count excode bytes
                excode += 1
                try:
                    code, payload = payload[0], payload[1:]
                    scode = ord2name.get(code)
                except IndexError:
                    pass
            if code < 0x80:
                # This is a single-byte code
                try:
                    value, payload = payload[0], payload[1:]
                except IndexError:
                    pass
                if scode in ['POOR_SIGNAL', 'ATTENTION', 'MEDITATION', 'BLINK']:
                    # Poor signal
                    if scode=='POOR_SIGNAL':
                        if value==0: # 0 - is ok!
                            continue
                        self.signal = value

                    self.state[scode] = value
                    print(scode, value)

            else:
                # This is a multi-byte code
                try:
                    vlength, payload = payload[0], payload[1:]
                except IndexError:
                    continue
                value, payload = payload[:vlength], payload[vlength:]
                # Multi-byte EEG and Raw Wave codes not included
                # Raw Value added due to Mindset Communications Protocol
                if scode == 'RAW_VALUE':
                    continue
                    '''

                    if vlength==2:
                        try:
                            raw = struct.unpack('>h', value)[0]

                            #raw = value[0] * 256 + value[1]
                            #if (raw >= 32768):
                            #    raw = raw - 65536

                            #print(scode, raw)
                            bytes = struct.pack('diiii', time(), raw, self.state['POOR_SIGNAL'], self.state['MEDITATION'], self.state['ATTENTION'])
                            self.dump_file.write(bytes)
                        except:
                            pass

                    else:
                        print(scode, f'wtf! vlength=={vlength}')
                        '''
                elif scode == 'FREQS':
                    bytes2write = b''
                    try:
                        freqs = EEGPowerData(*struct.unpack('>8L', b''.join(b'\x00' + value[o:o + 3] for o in range(0, 24, 3))))
                        print(f'freqs {freqs}')
                        bytes2write = struct.pack('d'+'iiiiiiii'+'iii', time(), *freqs, self.state['POOR_SIGNAL'], self.state['MEDITATION'],
                                        self.state['ATTENTION'])
                    except:
                        pass
                    
                    if bytes2write:
                        self.dump_file.write(bytes2write)


                if scode in ['HEADSET_CONNECTED','HEADSET_NOT_FOUND','HEADSET_DISCONNECTED']:
                    # Headset connect success
                    print(scode, value.encode('hex'))

                elif scode == 'REQUEST_DENIED':
                    # Request denied
                    print(scode)

                elif scode == 'STANDBY_SCAN':
                    # Standby/Scan mode
                    try:
                        byte = value[0]
                    except IndexError:
                        byte = None

                    if byte:
                        print(scode, 'STATUS_SCANNING')
                    else:
                        print(scode, 'STATUS_STANDBY')


if __name__ == '__main__':
    # chmod a+rw /dev/rfcomm0
    
    if os.name == 'nt':
        comstr = 'COM0'
    elif os.name == 'posix':
        comstr = '/dev/rfcomm0'
    else:
        raise Exception('WTF!')
        
    with Device(comstr) as d:
        d.run()


    # with SerialAutoDiscover() as device:
    #    pass
    # print()
