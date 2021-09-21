import ctypes
import threading
import queue
import struct
import time
import sys

hk32 = ctypes.windll.LoadLibrary('kernel32.dll')

PIPE_ACCESS_DUPLEX =                    0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE =         0x00080000
PIPE_TYPE_BYTE =                        0x00000000
PIPE_TYPE_MESSAGE =                     0x00000004
PIPE_READMODE_MESSAGE =                 0x00000002
OPEN_EXISTING =                         0x00000003
GENERIC_READ =                          0x80000000
GENERIC_WRITE =                         0x40000000
ERROR_MORE_DATA =                       234
ERROR_PIPE_CLOSED =                     109

if sys.maxsize > 2**32:
    def ctypes_handle(handle):
        return ctypes.c_ulonglong(handle)
else:
    def ctypes_handle(handle):
        return ctypes.c_uint(handle)

class ExhaustingPipe:

    def __init__(self, name):
        self.name = name
        self.isActive = False
        self.handle = hk32['CreateFileA'](
            ctypes.c_char_p(b'\\\\.\\pipe\\' + bytes(name, 'utf8')),
            ctypes.c_uint(GENERIC_READ | GENERIC_WRITE),
            0,                      # no sharing
            0,                      # default security
            ctypes.c_uint(OPEN_EXISTING),
            0,                      # default attributes
            0                       # no template file
        )

        if hk32['GetLastError']() != 0:
            err = hk32['GetLastError']()
            self.alive = False
            raise Exception(f"Pipe Open <\\\\.\\pipe\\{name}< Failed [{err}]")
            return

        xmode = struct.pack('I', PIPE_READMODE_MESSAGE)
        ret = hk32['SetNamedPipeHandleState'](
            ctypes_handle(self.handle),
            ctypes.c_char_p(xmode),
            ctypes.c_uint(0),
            ctypes.c_uint(0)
        )

        if ret == 0:
            err = hk32['GetLastError']()
            self.alive = False
            raise Exception('Pipe Set Mode Failed [%s]' % err)
            return

        self.bufSize = 4096
        self.isActive = True

    def close(self):
        if(self.handle):
            hk32['CloseHandle'](ctypes_handle(self.handle))
            self.isActive = False

    def _read_internal(self, expected):

        transactionBuffers = []
        retry = 10

        totalReceived = 0

        while(True):
            buf = ctypes.create_string_buffer(self.bufSize)
        
            msz = b'\x00\x00\x00\x00'
            ret = hk32['ReadFile'](ctypes_handle(self.handle), buf, self.bufSize, ctypes.c_char_p(msz), 0)

            if(ret == 0): 
                # get the last error 
                err = hk32['GetLastError'](ctypes_handle(self.handle))
                if (err == ERROR_PIPE_CLOSED):
                    self.close()
                    break
                if (err == ERROR_MORE_DATA):
                    # go ahead
                    pass
                elif (retry > 0):
                    retry -= 1
                    continue
                else:
                    self.close() # signal the pipe has closed
                    raise Exception('Broken Pipe / Failed to read')
            else:
                retry = 10
            
            countBytes = struct.unpack('I', msz)[0]

            # we're done reading
            if(countBytes == 0):
                break

            transactionBuffers.append((countBytes, buf))
            totalReceived += countBytes

            if(totalReceived < expected):
                continue
            
            if(totalReceived == expected):
                break
        
        acc = []
        totalCount = 0

        for countBytes, buf in transactionBuffers:
            acc.extend(buf[:countBytes])
            totalCount += countBytes

        return (bytes(acc), totalCount)
    
    def _write_internal(self, rawmsg):

        written = b'\x00\x00\x00\x00'

        ret = hk32['WriteFile'](
            ctypes_handle(self.handle), ctypes.c_char_p(rawmsg), 
            ctypes.c_uint(len(rawmsg)), 
            ctypes.c_char_p(written),
            ctypes.c_uint(0)
        )

        if ret == 0:
            self.close()        # signal the pipe has closed
            raise Exception('Broken Pipe / Failed to write')
        
        return struct.unpack('I', written)[0]
      

    def seaf_transaction(self, message):
        body_utf8 = message.encode(encoding='utf-8')

        header = struct.pack('=I', len(body_utf8)) # "I" for unsiged int
        
        # send the header first
        self._write_internal(header)
        
        # send the message in a second transaction
        self._write_internal(body_utf8)

        reply_size, cnt = self._read_internal(4)

        if(cnt != 4):
            raise ValueError(f"Unexpected response header size: {cnt} bytes")

        expected_message_length = struct.unpack('=I', reply_size)[0]
        
        # read it all
        message, cnt = self._read_internal(expected_message_length)

        if cnt != expected_message_length:
            raise ValueError(f"Got {cnt} bytes of reponse instead of expected {expected_message_length}")

        return message.decode(encoding='utf-8')


def getpipepath(name):
    return '\\\\.\\pipe\\' + name