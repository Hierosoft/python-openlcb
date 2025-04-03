'''
Example of raw socket communications over the physical connection, in this case
a socket.

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

from openlcb.canbus.gridconnectobserver import GridConnectObserver
from openlcb.tcplink.tcpsocket import TcpSocket

# specify connection information
# region replaced by settings
# host = "192.168.16.212"
# port = 12021
# endregion replaced by settings

sock = TcpSocket()
# s.settimeout(30)
sock.connect(settings['host'], settings['port'])

#######################

# send a AME frame in GridConnect string format with arbitrary source alias to
# elicit response
AME_packet_str = ":X10702001N;"
sock.sendString(AME_packet_str)
print("SR: {}".format(AME_packet_str.strip()))

observer = GridConnectObserver()

# display response - should be RID from node(s)
while True:  # have to kill this manually
    received = sock.receive()
    observer.push(received)
    if observer.hasNext():
        packet_str = observer.next()
        print("   RR: "+packet_str.strip())
