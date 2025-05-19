from timeit import default_timer

from logging import getLogger

from openlcb import precise_sleep
from openlcb.canbus.canlink import CanLink


logger = getLogger(__name__)


class CanLinkLayerSimulation(CanLink):
    # pumpEvents and waitForReady are based on examples
    #   and may be moved to CanLink or OpenLCBNetwork
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
            # self.physicalLayer must be set by canLink constructor by
            #   passing a physicalLayer to it.
            frame = self.physicalLayer.pollFrame()
            if not frame:
                break
            first = False
            string = frame.encodeAsString()
            print("      SENT (simulated socket) packet: "+string.strip())
            # ^ This is too verbose for this example (each is a
            #   request to read a 64 byte chunks of the CDI XML)
            # sock.sendString(string)
            self.physicalLayer.onFrameSent(frame)

    def waitForReady(self, run_physical_link_up_test=False):
        """
        Args:
            run_physical_link_up_test (bool): Set to True only
                if the last command that ran was
                "physicalLayerUp".
        Raises:
            AssertionError: run_physical_link_up_test is True
                but the state is not initially WaitingForSendCIDSequence
                or successive states were not triggered by pollState
                and onFrameSent.
        """
        self = self
        first = True
        state = self.pollState()
        print("[CanLinkLayerSimulation] waitForReady...state={}..."
              .format(state))
        first_state = state
        if run_physical_link_up_test:
            assert state == CanLink.State.WaitingForSendCIDSequence
        debug_count = 0
        second_state = None
        while True:
            debug_count += 1
            # print("{}. state: {}".format(debug_count, state))
            if state == CanLink.State.Permitted:
                # This could be the while condition, but
                #   is here so we can monitor it for testing.
                break
            if first is True:
                first = False
            if debug_count < 3:
                print("  * pumpEvents")
            self.pumpEvents()  # pass received data to physicalLayer&send queue
            if debug_count < 3:
                print("  * state: {}".format(state))
            state = self.getState()
            if first_state == CanLink.State.WaitingForSendCIDSequence:
                # State should be set by onFrameSent (called by
                # pumpEvents, or in non-simulation cases, the socket loop
                #   after dequeued and sent, as the next state is )
                if second_state is None:
                    assert state == CanLink.State.WaitForAliases, \
                        ("expected onFrameSent (if properly set to"
                         " handleFrameSent or overridden for simulation) sent"
                         " frame's EnqueueAliasAllocationRequest state (CID"
                         " 4's afterSendState), but state is {}"
                         .format(state))
                    second_state = state
                # If pumpEvents blocks for at least 200ms after send
                #   then receives, responses may have already been send
                #   to handleFrameReceived, in which case we may be in a
                #   later state. That isn't recommended except for
                #   realtime applications (or testing). However, if that
                #   is programmed, add
                #   `or state == CanLink.State.EnqueueAliasAllocationRequest`
                #   to the assertion.
            if state == CanLink.State.WaitForAliases:
                if debug_count < 3:
                    print("    * pumpEvents")
                self.pumpEvents()  # proceed to send: set _waitingForAliasStart
                # (prevent getWaitForAliasResponseStart() None in assert below)
            state = self.pollState()
            if state == CanLink.State.Permitted:
                print("    * state: {}".format(state))
                break
            st = self.getState()
            # print("  * state: {}".format(state))
            assert self.getWaitForAliasResponseStart() is not None, \
                "openlcb didn't send 7,6,5,4 CID frames (state={})".format(st)
            if ((default_timer() - self.getWaitForAliasResponseStart())
                    > CanLink.ALIAS_RESPONSE_DELAY):
                # 200ms = standard wait time for responses
                if not self.require_remote_nodes:
                    raise TimeoutError(
                        "In Standard require_remote_nodes=False mode,"
                        " but failed to proceed to Permitted state.")
            precise_sleep(.02)
            state = self.pollState()
        print("[CanLinkLayerSimulation] waitForReady...done")
