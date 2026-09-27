import asyncio
from httpx import ASGITransport, AsyncClient
from app.core.config import settings

async def test_suite():
    for env in ['production', 'local']:
        settings.ENVIRONMENT = env
        from app.main import create_app
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='https://api.ofc360.com') as client:
            # 1. Preflight OPTIONS
            r_opt = await client.request(
                'OPTIONS',
                '/api/v1/auth/login',
                headers={
                    'Origin': 'http://localhost:8080',
                    'Access-Control-Request-Method': 'POST',
                    'Access-Control-Request-Headers': 'content-type,authorization',
                }
            )
            print(f"[{env.upper()}] OPTIONS status: {r_opt.status_code}")
            print(f"[{env.upper()}] Allow-Origin: {r_opt.headers.get('access-control-allow-origin')}")
            print(f"[{env.upper()}] Allow-Credentials: {r_opt.headers.get('access-control-allow-credentials')}")
            print(f"[{env.upper()}] Allow-Methods: {r_opt.headers.get('access-control-allow-methods')}")
            print(f"[{env.upper()}] Allow-Headers: {r_opt.headers.get('access-control-allow-headers')}")
            assert r_opt.status_code == 200, f"Expected 200, got {r_opt.status_code}"
            assert r_opt.headers.get('access-control-allow-origin') == 'http://localhost:8080'
            assert r_opt.headers.get('access-control-allow-credentials') == 'true'

            # 2. POST /api/v1/auth/login with Origin header (e.g. invalid credentials returns 401, but WITH CORS header)
            r_post = await client.post(
                '/api/v1/auth/login',
                headers={'Origin': 'http://localhost:8080'},
                json={'email': 'nonexistent@ofc360.com', 'password': 'WrongPassword123!'}
            )
            print(f"[{env.upper()}] POST /login status: {r_post.status_code}")
            print(f"[{env.upper()}] POST Allow-Origin: {r_post.headers.get('access-control-allow-origin')}")
            print(f"[{env.upper()}] POST Allow-Credentials: {r_post.headers.get('access-control-allow-credentials')}")
            assert r_post.headers.get('access-control-allow-origin') == 'http://localhost:8080'
            assert r_post.headers.get('access-control-allow-credentials') == 'true'

    print("\nALL PREFLIGHT AND CORS TESTS PASSED PERFECTLY IN BOTH PROD AND LOCAL!")

if __name__ == '__main__':
    asyncio.run(test_suite())
