from typing import Optional

from jaeger_client.span_context import SpanContext  # type: ignore
from jaeger_client.tracer import Tracer  # type: ignore
from opentracing import InvalidCarrierException, SpanContextCorruptedException  # type: ignore
from opentracing.ext import tags  # type: ignore
from opentracing.propagation import Format  # type: ignore
from opentracing.scope import Scope  # type: ignore

from rap.common.utils import Constant
from rap.server.model import Request, Response, ServerMsgProtocol
from rap.server.plugin.processor.base import BaseProcessor


class TracingProcessor(BaseProcessor):
    def __init__(self, tracer: Tracer, scope_cache_timeout: Optional[float] = None):
        self._tracer: Tracer = tracer
        self._scope_cache_timeout: float = scope_cache_timeout or 60.0

    def _create_scope(self, msg: ServerMsgProtocol) -> Scope:
        span_ctx: Optional[SpanContext] = None
        header_dict: dict = {}
        for k, v in msg.header.items():
            header_dict[k.lower()] = v
        try:
            span_ctx = self._tracer.extract(Format.HTTP_HEADERS, header_dict)
        except (InvalidCarrierException, SpanContextCorruptedException):
            pass

        scope = self._tracer.start_active_span(str(msg.target), child_of=span_ctx, finish_on_close=True)
        scope.span.set_tag(tags.SPAN_KIND, tags.SPAN_KIND_RPC_SERVER)
        scope.span.set_tag(tags.PEER_SERVICE, msg.app.server_name)
        scope.span.set_tag(tags.PEER_HOSTNAME, ":".join([str(i) for i in msg.header["host"]]))
        scope.span.set_tag("correlation_id", msg.correlation_id)
        scope.span.set_tag("msg_type", msg.msg_type)
        return scope

    async def process_request(self, request: Request) -> Request:
        scope: Scope = self._create_scope(request)
        if request.msg_type is Constant.MSG_REQUEST:
            self.app.cache.add(f"{self.__class__.__name__}:{request.correlation_id}", self._scope_cache_timeout, scope)
        else:
            scope.close()
        return request

    async def process_response(self, response: Response) -> Response:
        if response.msg_type is Constant.MSG_RESPONSE:
            scope: Scope = self.app.cache.get(f"{self.__class__.__name__}:{response.correlation_id}")
            status_code: int = response.status_code
            scope.span.set_tag("status_code", status_code)
            scope.span.set_tag(tags.ERROR, status_code == 200)
            scope.close()
        else:
            scope = self._create_scope(response)
            scope.close()
        return response
