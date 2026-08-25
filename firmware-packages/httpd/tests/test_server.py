import asyncio

import pytest

from httpd import server as server_module

_BODY = b"<html>hello</html>"


def test_a_registered_page_is_served_with_its_prebuilt_headers(server, serve):
    server.page("/", _BODY)

    response = serve(server, b"GET / HTTP/1.1\r\nHost: board\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: text/html; charset=utf-8\r\n" in response
    assert b"Content-Length: " + str(len(_BODY)).encode() + b"\r\n" in response
    assert b"Cache-Control: no-cache\r\n" in response
    assert response.endswith(b"\r\n\r\n" + _BODY)


def test_a_pre_compressed_page_announces_its_encoding(server, serve):
    server.page("/", _BODY, encoding="gzip")

    response = serve(server, b"GET / HTTP/1.1\r\n\r\n")

    assert b"Content-Encoding: gzip\r\n" in response
    assert response.endswith(_BODY)


def test_a_page_can_declare_its_own_content_type(server, serve):
    server.page("/data", b"{}", content_type="application/json")

    response = serve(server, b"GET /data HTTP/1.1\r\n\r\n")

    assert b"Content-Type: application/json\r\n" in response


def test_head_returns_the_headers_without_the_body(server, serve):
    server.page("/", _BODY)

    response = serve(server, b"HEAD / HTTP/1.1\r\n\r\n")

    assert response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Length: " + str(len(_BODY)).encode() + b"\r\n" in response
    assert _BODY not in response


def test_a_query_string_still_reaches_the_page(server, serve):
    server.page("/", _BODY)

    response = serve(server, b"GET /?refresh=1 HTTP/1.1\r\n\r\n")

    assert response.endswith(_BODY)


def test_an_unknown_path_is_not_found(server, serve):
    server.page("/", _BODY)

    assert serve(server, b"GET /missing HTTP/1.1\r\n\r\n") == server_module._NOT_FOUND


def test_a_write_to_a_page_is_not_allowed(server, serve):
    server.page("/", _BODY)

    assert serve(server, b"POST / HTTP/1.1\r\n\r\n") == server_module._NOT_ALLOWED


@pytest.mark.parametrize(
    "request_bytes",
    [
        pytest.param(b"", id="nothing at all"),
        pytest.param(b"GET\r\n\r\n", id="no path"),
        pytest.param(b"GET /" + b"x" * 300 + b" HTTP/1.1\r\n\r\n", id="request line too long"),
        pytest.param(b"GET / HTTP/1.1\r\nX: " + b"y" * 300 + b"\r\n\r\n", id="header too long"),
        pytest.param(
            b"GET / HTTP/1.1\r\n" + b"".join(b"H%d: v\r\n" % i for i in range(40)) + b"\r\n",
            id="too many headers",
        ),
    ],
)
def test_a_malformed_request_is_rejected(server, serve, request_bytes):
    server.page("/", _BODY)

    assert serve(server, request_bytes) == server_module._BAD_REQUEST


def test_a_connection_is_closed_and_forgotten_after_every_request(server, reader, writer):
    server.page("/", _BODY)
    sink = writer()

    asyncio.run(server._handle(reader(b"GET / HTTP/1.1\r\n\r\n"), sink))

    assert sink.closed
    assert sink.waited
    assert server._connections == []


def test_a_peer_that_drops_mid_response_does_not_escape_the_handler(server, reader, writer):
    server.page("/", _BODY)
    sink = writer(fail_on_write=True)

    asyncio.run(server._handle(reader(b"GET / HTTP/1.1\r\n\r\n"), sink))

    assert sink.closed
    assert server._connections == []


def test_a_socket_already_torn_down_still_leaves_the_connection_forgotten(server, reader, writer):
    server.page("/", _BODY)
    sink = writer(fail_on_wait_closed=True)

    asyncio.run(server._handle(reader(b"GET / HTTP/1.1\r\n\r\n"), sink))

    assert sink.waited
    assert server._connections == []


def test_start_binds_the_port_once(server, listener):
    async def _scenario():
        await server.start()
        await server.start()

    assert not server.running
    asyncio.run(_scenario())

    assert server.running
    assert len(listener) == 1
    assert listener[0].port == 8080
    assert listener[0].address == server_module._BIND_ADDRESS
    assert listener[0].backlog == server_module._BACKLOG


def test_stop_closes_the_listener_and_every_open_connection(server, listener, writer):
    server.page("/", _BODY)
    broadcast = server.stream("/ws")
    sink = writer()

    async def _scenario():
        await server.start()
        server._connections.append(sink)
        await server.stop()
        await server.stop()

    asyncio.run(_scenario())

    assert not server.running
    assert listener[0].closed
    assert listener[0].waited
    assert sink.closed
    assert broadcast._clients == []


def test_a_stopped_server_can_be_started_again(server, listener):
    async def _scenario():
        await server.start()
        await server.stop()
        await server.start()

    asyncio.run(_scenario())

    assert server.running
    assert len(listener) == 2
