
from .rpcclient import SeafileRpcClient as RpcClient
from .tipi_rpcclient import TipiSeafileRpcClient as TipiWinRpcClient

class TaskType(object):
    DOWNLOAD = 0
    UPLOAD = 1
