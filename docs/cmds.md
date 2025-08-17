# 1) Instalar
pip install fastapi uvicorn python-dotenv

# 2) Ejecutar (desde el directorio del proyecto)
uvicorn app_mt:app --reload

# 3) Swagger
http://127.0.0.1:8000/docs

# 4) Crear tenant (admin)
curl -s -X POST http://127.0.0.1:8000/tenants \
  -H 'X-Admin-Key: local-admin-123' \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"acme","name":"Acme Inc."}' | jq

# Guarda la api_key devuelta (se muestra una vez)

# 5) Ingestar docs (stub)
curl -s -X POST http://127.0.0.1:8000/tenants/acme/docs \
  -H 'X-API-Key: <API_KEY_AQUI>' \
  -H 'Content-Type: application/json' \
  -d '{"documents":[{"text":"Hola mundo","source":"nota.txt"}]}' | jq

# 6) Consultar (stub)
curl -s -X POST http://127.0.0.1:8000/tenants/acme/ask \
  -H 'X-API-Key: <API_KEY_AQUI>' \
  -H 'Content-Type: application/json' \
  -d '{"query":"¿Qué hay en la base?","top_k":3}' | jq