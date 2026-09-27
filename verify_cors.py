import asyncio
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from app.core.config import settings

async def test_suite():
    from app.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url='https://api.ofc360.com') as client:
        # 1. Test OPTIONS preflight for /api/v1/auth/login with Origin: http://localhost:8080
        r_opt = await client.request(
            'OPTIONS',
            '/api/v1/auth/login',
            headers={
                'Origin': 'http://localhost:8080',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,authorization',
            }
        )
        print(f"[PREFLIGHT OPTIONS] Status: {r_opt.status_code}")
        print(f"[PREFLIGHT OPTIONS] Allow-Origin: {r_opt.headers.get('access-control-allow-origin')}")
        print(f"[PREFLIGHT OPTIONS] Allow-Credentials: {r_opt.headers.get('access-control-allow-credentials')}")
        print(f"[PREFLIGHT OPTIONS] Allow-Methods: {r_opt.headers.get('access-control-allow-methods')}")
        print(f"[PREFLIGHT OPTIONS] Allow-Headers: {r_opt.headers.get('access-control-allow-headers')}")
        assert r_opt.status_code == 200, f"Expected 200, got {r_opt.status_code}"
        assert r_opt.headers.get('access-control-allow-origin') == 'http://localhost:8080'
        assert r_opt.headers.get('access-control-allow-credentials') == 'true'

        # 2. Test OPTIONS preflight for 127.0.0.1:8080
        r_opt_127 = await client.request(
            'OPTIONS',
            '/api/v1/auth/login',
            headers={
                'Origin': 'http://127.0.0.1:8080',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,authorization',
            }
        )
        assert r_opt_127.status_code == 200
        assert r_opt_127.headers.get('access-control-allow-origin') == 'http://127.0.0.1:8080'
        assert r_opt_127.headers.get('access-control-allow-credentials') == 'true'

        # 3. Test OPTIONS preflight for https://ofc360.com
        r_opt_prod = await client.request(
            'OPTIONS',
            '/api/v1/auth/login',
            headers={
                'Origin': 'https://ofc360.com',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,authorization',
            }
        )
        assert r_opt_prod.status_code == 200
        assert r_opt_prod.headers.get('access-control-allow-origin') == 'https://ofc360.com'
        assert r_opt_prod.headers.get('access-control-allow-credentials') == 'true'

        # 4. Test OPTIONS preflight for https://www.ofc360.com
        r_opt_www = await client.request(
            'OPTIONS',
            '/api/v1/auth/login',
            headers={
                'Origin': 'https://www.ofc360.com',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,authorization',
            }
        )
        assert r_opt_www.status_code == 200
        assert r_opt_www.headers.get('access-control-allow-origin') == 'https://www.ofc360.com'
        assert r_opt_www.headers.get('access-control-allow-credentials') == 'true'

        # 5. Test POST /api/v1/auth/login returns CORS headers on responses (even 401/422 error response)
        r_post = await client.post(
            '/api/v1/auth/login',
            headers={'Origin': 'http://localhost:8080'},
            json={'email': 'nonexistent@ofc360.com', 'password': 'WrongPassword123!'}
        )
        print(f"\n[POST /login] Status: {r_post.status_code}")
        print(f"[POST /login] Allow-Origin: {r_post.headers.get('access-control-allow-origin')}")
        print(f"[POST /login] Allow-Credentials: {r_post.headers.get('access-control-allow-credentials')}")
        assert r_post.headers.get('access-control-allow-origin') == 'http://localhost:8080'
        assert r_post.headers.get('access-control-allow-credentials') == 'true'

    print("\nALL PREFLIGHT AND CORS TESTS PASSED 100% SUCCESFULLY!")

if __name__ == '__main__':
    asyncio.run(test_suite())
