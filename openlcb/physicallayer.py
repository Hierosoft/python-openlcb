'''
Generalize access to the physical layer;.

Parent of `CanPhysicalLayer`

To change implementation of popFrames or other methods without
NotImplementedError, call super() normally, as such methods are used
similarly to how a template or generic class would be used in a strictly
OOP language. However, re-implementation is typically not necessary
since Python allows any type to be used for the elements of _sends.

We implement logic here not only because it is convenient but also
because _sends (and the subclass being a state machine with states
specific to the physical layer type) is a the paradigm used by this
openlcb stack (Python module) as a whole (connection and flow determined
by application's port code, state determined by the openlcb stack). This
allows single-threaded use or thread-safe multi-threaded use like the C
version of openlcb in OpenMRN. Issue #62 comments discuss this paradigm
(among other necessary structure beyond that) as central to stability
and predictable use in applications.
-Poikilos
'''


from collections import deque


class PhysicalLayer:
    """Generalize access to the physical layer;.

    Parent of `CanPhysicalLayer`

    The PhysicalLayer class enforces restrictions on how many node instances
    can be created on a single machine.

    If you need more than one node (such as to create virtual nodes), call:
    ```
    PhysicalLayer.moreThanOneNodeOnMyMachine(count)
    ```
    with `count` higher than 1.

    If you did that and this warning still appears, set:
    ```
    PhysicalLayer.allowDynamicNodes(true)
    ```
    ONLY if you are really sure you require the number of nodes *on this machine*
    (*not* including remote network nodes) to be more or less at different times
    (and stack memory allocations don't need to be manually optimized on
    the target platform).
    """

    def __init__(self):
        self._sends = deque()

    def sendFrameAfter(self, frame):
        """Enqueue: *IMPORTANT* Main/other thread may have
        called this. Any other thread sending other than the _listen
        thread is bad, since overlapping calls to socket cause undefined
        behavior, so this just adds to a deque (double ended queue, used
        as FIFO).
        - CanPhysicalLayerGridConnect constructor sets
          canSendCallback, and CanLink sets canSendCallback to this
          (formerly set to a sendToPort function which was formerly a
          direct call to a port which was not thread-safe)
          - Add a generalized LocalEvent queue avoid deep callstack?
            - See issue #62 comment about a local event queue.
              For now, CanFrame is used (improved since issue #62
              was solved by adding more states to CanLink so it
              can have incremental states instead of requiring two-way
              communication [race condition] during a single
              blocking call to defineAndReserveAlias)
        """
        self._sends.appendleft(frame)

    def popFrames(self):
        """empty and return content of _sends
        Subclass may reimplement this or enforce types after calling
        frames = PhysicalLayer.popFrames(self) (or use super)
        Then return frames.
        """
        frames = deque()
        startCount = self._sends
        frame = True
        # Do them one at a time to make *really* sure someone else isn't
        #   editing _sends (it would be a shame if we set frames =
        #   self._sends and set self._frames = deque() and another
        #   thread pushed to self._frames in between the two lines of
        #   code [possible even with GIL probably, since they are
        #   separate lines]--then the data would be lost).
        try:
            while True:
                if len(self._sends) > startCount:
                    raise InterruptedError(
                        "the openlcb stack must be controlled by only one"
                        " thread (typically the socket thread for"
                        " predictability and thread safety) but _sends"
                        " increased during popFrames"
                        "(don't call pollState until return from"
                        " popFrames, or before calling it)")
                frame = self._sends.pop()  # pop is from right
                frames.appendleft(frame)
        except IndexError as ex:
            if str(ex) != "pop from an empty queue":
                raise
            # else everything is ok (no more frames to get)

            # Stop is done with the exception to avoid a race condition
            #   between `while len(_sends) > 0` and other operations and
            #   checks during the loop.
        return frames

    def pollFrame(self):
        return self._sends.pop()

    def physicalLayerUp(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerRestart(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def physicalLayerDown(self):
        """abstract method"""
        raise NotImplementedError("Each subclass must implement this.")

    def encodeFrameAsString(self, frame) -> str:
        raise NotImplementedError("Each subclass must implement this.")
