# what a stage raises to tell the queue how its job ended; stages raise these without knowing the handlers


# waiting for something outside the job; it does not spend an attempt
class Deferred(Exception):
    def __init__(self, message: str, delay_seconds: int = 60):
        super().__init__(message)
        self.delay_seconds = delay_seconds


# a failure retries cannot fix
class Final(Exception):
    pass
