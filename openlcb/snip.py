
import logging


class SNIP:
    '''Holds the Simple Node Information Protocol values or blank strings.

    Provides support for loading via short or long messages. A SNIP is
    write-once; when the underlying connection resets, a new SNIP struct should
    be installed in the node.

    Args:
        mfgName (str, optional): The manufacturer name for the node
            (vendor or creator of device).
        model (str, optional): The model name of the node, indicating a
            specific product.
        hVersion (str, optional): The hardware version identifier
            (physical revision of the hardware).
        sVersion (str, optional): The software version identifier.
            Indicates the firmware or control software version running
            on the node.
        uName (str, optional): The user-provided node name. This can be
            customized by the user to provide a recognizable identifier for
            the node.
        uDesc (str, optional): The user-provided description for the node.
            This provides additional information about the node's function or
            location.
    '''

    def __init__(self, mfgName="",
                 model="",
                 hVersion="",
                 sVersion="",
                 uName="",
                 uDesc=""):
        self.manufacturerName = mfgName
        self.modelName = model
        self.hardwareVersion = hVersion
        self.softwareVersion = sVersion
        self.userProvidedNodeName = uName
        self.userProvidedDescription = uDesc

        self.data = bytearray([0]*253)
        self.index = 0

        self.updateSnipDataFromStrings()
        self.index = 0

    # OpenLCB Strings are fixed length null terminated.
    # We don't (yet) support later versions with e.g. larger strings, etc.

    def getStringN(self, n):
        '''
        Get the desired string by string number in the data.

        Args:
            n (int):  0-based number of the String
        Returns:
            str: Requested String up to but not including the terminating zero
                byte
        '''
        start = self.findString(n)
        length = 0
        if n in (0, 1):
            length = 41
        elif n in (2, 3):
            length = 21
        elif n == 4:
            length = 63
        elif n == 5:
            length = 64
        else:
            logging.error("Unexpected string request: {}".format(n))
            return ""
        return self.getString(start, length)

    def findString(self, n):
        '''
        Find start index of the nth string.

        Zero indexed.
        Is aware of the 2nd version code byte.
        Logs and returns -1 if the string isn't found within the buffer
        '''

        if n == 0:
            return 1  # first one is automatic
        retval = 1
        stringCount = 0
        # scan over the buffer
        for i in range(1, 252):
            # checking for an end-of-string mark
            if self.data[i] == 0:
                # found one - this ends the stringCount string
                # if that's the request, return start
                if stringCount == n:
                    return retval
                # if not, the _next_ character starts the next string
                retval = i+1
                stringCount += 1
                # special case for the 5th string
                if stringCount == 4:
                    i += 1
                    retval += 1
        # fell out without finding
        return 0

    def getString(self, first, maxLength):
        """Get the string at index `first`
        ending with either a null or having maxLength,
        whichever comes first.

        Args:
            first (int): Where in data to start.
            maxLength (int): Maximum length of string to return.

        Returns:
            str: The string decoded as UTF-8 from data bytes.
        """
        null_i = self.data.find(b'\0', first)
        terminate_i = first + maxLength
        if null_i > -1:
            terminate_i = min(null_i, terminate_i)
        # terminate_i should point at the first zero or exclusive end
        return self.data[first:terminate_i].decode("utf-8")

    def addData(self, in_data):
        '''
        Add additional bytes of SNIP data
        '''
        for i in range(0, len(in_data)):
            # protect against overlapping requests causing an overflow
            if (i+self.index) >= 253:
                logging.error("Overlapping SNIP requests, truncating")
                break
            self.data[i+self.index] = in_data[i]
        self.index += len(in_data)
        self.updateStringsFromSnipData()

    def updateStringsFromSnipData(self):
        '''
        Load strings from current SNIP accumulated data
        '''
        self.manufacturerName = self.getStringN(0)
        self.modelName = self.getStringN(1)
        self.hardwareVersion = self.getStringN(2)
        self.softwareVersion = self.getStringN(3)

        self.userProvidedNodeName = self.getStringN(4)
        self.userProvidedDescription = self.getStringN(5)

    def updateSnipDataFromStrings(self):
        '''
        Store strings into SNIP accumulated data
        '''
        # clear string
        self.data = bytearray([0]*253)

        self.index = 1  # next storage location
        self.data[0] = 4  # first part version

        # mfgArray = Data(manufacturerName.utf8.prefix(40))
        # ^ leave one space for zero
        mfgArray = '{:.40}'.format(self.manufacturerName).encode('utf-8')
        if len(mfgArray) > 0 :
            for i in range(0, len(mfgArray)):
                self.data[self.index] = mfgArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

        # mdlArray = Data(modelName.utf8.prefix(40))
        mdlArray = '{:.40}'.format(self.modelName).encode('utf-8')
        if len(mdlArray) > 0:
            for i in range(0, len(mdlArray)):
                self.data[self.index] = mdlArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

        # hdvArray = Data(hardwareVersion.utf8.prefix(20))
        hdvArray = '{:.20}'.format(self.hardwareVersion).encode('utf-8')
        if len(hdvArray) > 0:
            for i in range(0, len(hdvArray)):
                self.data[self.index] = hdvArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

        # sdvArray = Data(softwareVersion.utf8.prefix(20))
        sdvArray = '{:.20}'.format(self.softwareVersion).encode('utf-8')
        if len(sdvArray) > 0 :
            for i in range(0, len(sdvArray)):
                self.data[self.index] = sdvArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

        self.data[self.index] = 2
        self.index += 1

        # upnArray = Data(userProvidedNodeName.utf8.prefix(62))
        upnArray = '{:.62}'.format(self.userProvidedNodeName).encode('utf-8')
        if len(upnArray) > 0 :
            for i in range(0, len(upnArray)):
                self.data[self.index] = upnArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

        # updArray = Data(userProvidedDescription.utf8.prefix(63))
        updArray = \
            '{:.63}'.format(self.userProvidedDescription).encode('utf-8')
        if len(updArray) > 0 :
            for i in range(0, len(updArray)):
                self.data[self.index] = updArray[i]
                self.index += 1

        self.data[self.index] = 0
        self.index += 1

    def returnStrings(self):
        '''copy out until the 6th zero byte'''
        stop = self.findString(6)
        retval = bytearray([0]*stop)
        if stop == 0:
            return retval
        for i in range(0, stop-1):
            retval[i] = self.data[i]
        return retval
