'''
Example of raw socket communications over the physical connection, in this case
a serial port.

Usage:
python3 example_string_interface.py [host|host:port]

Options:
host|host:port            (optional) Set the address (or using a colon,
                          the address and port). Defaults to a hard-coded test
                          address and port.
'''
# region same code as other examples
from examples_settings import Settings  # do 1st to fix path if no pip install
settings = Settings()

if __name__ == "__main__":
    settings.load_cli_args(docstring=__doc__)
# endregion same code as other examples

from openlcb import precise_sleep  # noqa: E402
from openlcb.canbus.gridconnectobserver import GridConnectObserver  # noqa:E402
from openlcb.canbus.seriallink import SerialLink  # noqa: E402

# specify connection information
# region replaced by settings
# device = "/dev/cu.usbmodemCC570001B1"
# endregion replaced by settings


sock = SerialLink()
sock.connectLocal(settings['device'])

#######################

# send a AME frame in GridConnect string format with arbitrary source alias to
# elicit response
AME = ":X10702001N;"
sock.sendString(AME)
print("SR: {}".format(AME.strip()))

observer = GridConnectObserver()

# display response - should be RID from node(s)
while True:  # have to kill this manually
    received = sock.receive()
    if received is not None:
        observer.push(received)
        if observer.hasNext():
            packet_str = observer.next()
            print("   RR: "+packet_str.strip())
    # canLink.pollState()

    # while True:
    #     frame = physicalLayer.pollFrame()
    #     if frame is None:
    #         break
    #     sock.sendString(frame.encodeAsString())
    #     physicalLayer.onFrameSent(frame)
    precise_sleep(.01)
