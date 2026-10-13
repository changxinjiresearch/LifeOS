"""NextPlan v14: optional Issue inbox relay plus staged private-DB Direct API.

Legacy NextPlan state remains canonical until a separately verified cutover.
"""
import asyncio
import json
from . import server_v13 as legacy
from . import direct_v3_http as direct
from . import inbox_relay_v1 as inbox

async def _reply(send,status,data):
    await send({"type":"http.response.start","status":status,"headers":[
        (b"content-type",b"application/json"),(b"cache-control",b"no-store")]})
    await send({"type":"http.response.body","body":json.dumps(data).encode()})

async def app(scope,receive,send):
    if scope.get("type")=="lifespan":
        tasks=[]
        async def wrapped_receive():
            message=await receive()
            if message["type"]=="lifespan.startup" and not tasks:
                tasks.extend([asyncio.create_task(direct.periodic_reconcile()),
                              asyncio.create_task(inbox.poll_loop())])
            elif message["type"]=="lifespan.shutdown":
                for task in tasks:task.cancel()
                if tasks:await asyncio.gather(*tasks,return_exceptions=True)
                tasks.clear()
            return message
        try:
            return await legacy.app(scope,wrapped_receive,send)
        finally:
            for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    if scope.get("type")=="http":
        path=str(scope.get("path",""))
        method=scope.get("method","GET")
        if path=="/inbox/v1/status" and method=="GET":
            return await _reply(send,200,{"enabled":inbox.enabled(),**inbox.health})
        if path.startswith("/inbox/v1/receipt/") and method=="GET":
            raw=path.removeprefix("/inbox/v1/receipt/")
            if not raw.isdecimal() or len(raw)>12:
                return await _reply(send,400,{"error":"invalid_issue_number"})
            try:
                result=await inbox.receipt(int(raw))
                return await _reply(send,200,result)
            except Exception:
                return await _reply(send,503,{"error":"verification_unavailable"})
        if path.startswith(direct.PREFIX+"/"):
            return await direct.handle(scope,receive,send)
    return await legacy.app(scope,receive,send)

mcp=legacy.mcp
