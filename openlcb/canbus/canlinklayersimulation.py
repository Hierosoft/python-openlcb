from timeit import default_timer

from openlcb import precise_sleep
from openlcb.canbus.canlink import CanLink


class CanLinkLayerSimulation(CanLink):
    # pumpEvents and waitForReady are based on examples
    #   and may be moved to CanLink or Dispatcher
    #   to make the Python module easier to use.

    def pumpEvents(self):
        # try:
        #     received = sock.receive()
        #     if received is not None:
        #         if settings['trace']:
        #             observer.push(received)
        #             if observer.hasNext():
        #                 packet_str = observer.next()
        #                 # print("   RR: "+packet_str.strip())
        #                 # ^ commented since MyHandler shows parsed XML
        #                 #   fields instead
        #         # pass to link processor
        #         physicalLayer.handleData(received)
        # except BlockingIOError:
        #     pass
        self.pollState()
        while True:
            frame = self.physicalLayer.pollFrame()
            if not frame:
                break
            string = frame.encodeAsString()
            # print("      SENT packet: "+string.strip())
            # ^ This is too verbose for this example (each is a
            #   request to read a 64 byte chunks of the CDI XML)
            # sock.sendString(string)
            self.physicalLayer.onSentFrame(frame)

    def waitForReady(self):
        print("[CanLink] waitForReady...")
        self = self
        while self.pollState() != CanLink.State.Permitted:
            self.pumpEvents()  # provides incoming data to physicalLayer & sends queued
            if self.getState() == CanLink.State.WaitForAliases:
                self.pumpEvents()  # prevent assertion error below, proceed to send.
            if self.pollState() == CanLink.State.Permitted:
                break
            assert self.getWaitForAliasResponseStart() is not None, \
                "openlcb didn't send the 7,6,5,4 CID frames (state={})".format(self.getState())
            if default_timer() - self.getWaitForAliasResponseStart() > CanLink.ALIAS_RESPONSE_DELAY:
                # 200ms = standard wait time for responses
                if not self.require_remote_nodes:
                    raise TimeoutError(
                        "In Standard require_remote_nodes=False mode,"
                        " but failed to proceed to Permitted state.")
            precise_sleep(.02)
        print("[CanLink] waitForReady...done")
