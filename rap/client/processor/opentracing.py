from typing import Optional

from jaeger_client.tracer import Tracer  # type: ignore
from jaeger_client.span_context import SpanContext  # type: ignore
from opentracing import InvalidCarrierException, SpanContextCorruptedException  # type: ignore
from opentracing.propagation import Format  # type: ignore
from opentracing.scope import Scope  # type: ignore
from opentracing.ext import tags  # type: ignore

from rap.server.model import RequestModel, ResponseModel
from rap.server.processor.base import BaseProcessor


class TracingProcessor(BaseProcessor):
    def __init__(self, tracer: Tracer):
        self._tracer: Tracer = tracer
        self._scope: Optional[Scope] = None

    async def process_request(self, request: RequestModel) -> RequestModel:
        span_ctx: Optional[SpanContext] = None
        header_dict: dict = {}
        for k, v in request.header.items():
            header_dict[k.lower()] = v
        try:
            span_ctx = self._tracer.extract(Format.HTTP_HEADERS, header_dict)
        except (InvalidCarrierException, SpanContextCorruptedException):
            pass

        self._scope = self._tracer.start_active_span(
            str(request.func_name), child_of=span_ctx, finish_on_close=True
        )
        self._scope.span.set_tag(tags.SPAN_KIND, tags.SPAN_KIND_RPC_CLIENT)
        self._scope.span.set_tag(tags.PEER_SERVICE, request.func_name)
        self._scope.span.set_tag(tags.PEER_HOSTNAME, ":".join(request.header["host"]))
        self._scope.span.set_tag("group", request.group)
        self._scope.span.set_tag("num", request.num)
        return request

    async def process_response(self, response: ResponseModel) -> ResponseModel:
        if self._scope:
            status_code: int = response.header["status_code"]
            self._scope.span.set_tag("status_code", status_code)
            self._scope.span.set_tag(tags.ERROR, status_code == 200)
            self._scope.close()
        return response