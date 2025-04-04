class InternalEvent:
    """An event for internal use by the framework
    (framework state events)
    - Should be eventually all handled by Dispatcher so
      that it can handle state ("runlevel") as per issue #62.
    - For OpenLCB/LCC Events, see Events that are not
      subclasses of this.
    """
    # TODO: move non-LCC MTI values to here.


class SendAliasReservationEvent(InternalEvent):
    """A CanFrame container representing an alias reservation attempt.
    Reserved for future use (For now, ignore each CanFrame from deque
    that has has alias in invalidAliases)

    Args:
        attempt_number (int): Specify the same attempt number for all
            frames in a single call to defineAndReserveAlias--required
            so lower-numbered attempts can be deleted from the deque
            when a new attempt is started.
    """
    attempt_counter = 0

    @classmethod
    def nextAttemptNumber(cls):
        """Get an alias reservation attempt number
        (See attempt_number constructor arg in class docstring).
        """
        cls.attempt_counter += 1  # ok since 0 is invalid
        return cls.attempt_counter

    def __init__(self, attempt_number, canFrame):
        self.attempt_number = attempt_number
        self.canFrame = canFrame
