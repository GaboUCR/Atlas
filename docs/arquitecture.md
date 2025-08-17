# Atlas — Requerimientos y Arquitectura (RAG Multi‑tenant)

> Plataforma de AI Engineering para búsqueda híbrida + RAG con evaluación continua, multi‑tenant y con observabilidad de punta a punta.

---

## 0. Visión

Construir una plataforma de **asistencia y búsqueda empresarial** que combine **búsqueda híbrida (BM25 + vectorial)**, **RAG** orquestado con flujos multi‑paso y **evaluación/observabilidad** continua, exponiendo una **API pública** y una **UI** usable por distintos **tenants** (organizaciones) con aislamiento fuerte, seguridad y SLAs de producción.

**Objetivos clave**

* Respuestas **con fundamento** (citas) y **baja alucinación**.
* Tiempo de respuesta **p95 ≤ 1.2s** para consultas típicas.
* **99.9%** de disponibilidad mensual.
* **Tuning continuo** (retrieval, prompts, modelos) basado en métricas.

---

## 1. Personas y casos de uso

**Personas**

* *Usuario final* (Soporte/Operaciones/Ventas): pregunta, recibe respuesta con citas.
* *Administrador de tenant* (IT/Knowledge): da de alta fuentes, permisos, políticas.
* *AI Engineer/Plataforma*: configura índices, evals, observa métricas, hace tuning.

**Casos de uso principales**

1. Pregunta ad‑hoc y respuesta con citas (multilingüe ES/EN).
2. Ingesta continua de documentos desde GDrive/Confluence/SharePoint/HTTP/S3.
3. Búsqueda híbrida con filtros por metadatos (fecha, tipo, confidencialidad).
4. RAG con verificador de citas y postproceso (formateo y políticas).
5. Panel de calidad (recall\@k, nDCG, groundedness, latencia, costo).
6. Auto‑tuning nocturno y despliegue seguro de mejoras (PRs/feature flags).

---

## 2. Alcance y fuera de alcance

**En alcance**

* Multi‑tenant (namespaces/índices por tenant) con RBAC.
* Conectores: HTTP, Google Drive, Confluence, SharePoint, S3 (MVP: HTTP + GDrive).
* Búsqueda híbrida (BM25 + vector) + reranker.
* Orquestación RAG (LangGraph) con verificador de grounding.
* Observabilidad (trazas, métricas, costos) + evaluación (Ragas + golden set).
* API pública (OpenAPI), UI web (chat + búsqueda + administración).

**Fuera de alcance (MVP)**

* Edición colaborativa de documentos.
* Escritura en sistemas fuente (solo lectura).
* Garantías criptográficas de procedencia (se pueden planear a futuro).

---

## 3. Requerimientos funcionales (FR)

**FR‑1 Ingesta**

* FR‑1.1: Conectar fuente, programar *crawl* o *webhook* → cola de ingesta.
* FR‑1.2: Parsing robusto: PDF (OCR si escaneado), HTML, DOCX, TXT.
* FR‑1.3: Limpieza, normalización, *dedupe*, *chunking* semántico.
* FR‑1.4: Metadatos: `source, title, path, mime, created_at, updated_at, language, pii_tags, acl, version, hash`.
* FR‑1.5: Persistir *raw* y *clean* en lakehouse. Generar *embeddings*.

**Criterio de aceptación:** conecto un bucket HTTP/GDrive, se indexan ≥1k docs, el 100% aparece consultable con metadatos y *retries* ante errores.

**FR‑2 Indexado & búsqueda**

* FR‑2.1: Índice léxico (BM25) y vectorial (HNSW/IVF) por tenant.
* FR‑2.2: *Ensemble* (RRF) entre BM25 y vectorial.
* FR‑2.3: Filtros por metadatos y *ACL* por documento/chunk.
* FR‑2.4: Top‑k configurable, *reranker* *cross‑encoder* opcional.

**FR‑3 Orquestación RAG**

* FR‑3.1: Flujo: *Detect Idioma → Retrieve → Rerank → Grounding → LLM → Verificador de citas → Postproceso*.
* FR‑3.2: Si grounding insuficiente, reintento con expansión semántica (consulta booleana + sinonimia) y/o aumentar *k*.
* FR‑3.3: Devolver citas (pasajes) con offsets y puntuaciones.

**FR‑4 UI y API**

* FR‑4.1: UI de chat con citas resaltadas y vista de pasajes.
* FR‑4.2: UI de administración (fuentes, metadatos, políticas, evals).
* FR‑4.3: API: `/v1/chat`, `/v1/retrieval/search`, `/v1/docs/ingest`, `/v1/tenants`, `/v1/evals/run`, `/v1/metrics`.

**FR‑5 Observabilidad & Evaluación**

* FR‑5.1: Trazas por *span* (retrieve, rerank, llm), costos y tokens.
* FR‑5.2: Métricas: latencia p50/p95/p99, QPS, errores, costos, cache hit.
* FR‑5.3: Evaluación: recall\@k, nDCG\@k, groundedness, answer‑relevance, utilidad percibida.
* FR‑5.4: Panel de calidad por tenant y *global*.

**FR‑6 Seguridad & Tenancy**

* FR‑6.1: Auth: OAuth2/JWT. RBAC por rol (admin, editor, viewer, auditor).
* FR‑6.2: Aislamiento por tenant: namespaces/buckets/índices; claves KMS por tenant.
* FR‑6.3: PII redaction (ingesta) y *content firewall* en consulta.
* FR‑6.4: Auditoría: quién accedió a qué y cuándo.

---

## 4. Requerimientos no funcionales (NFR)

| Categoría      | NFR                                                                |
| -------------- | ------------------------------------------------------------------ |
| Rendimiento    | p95 ≤ 1.2s (consulta → respuesta) con cache tibio; p99 ≤ 2.5s      |
| Disponibilidad | ≥ 99.9% mensual                                                    |
| Escalabilidad  | ≥ 100 QPS sostenido (MVP) con *horizontal scaling*                 |
| Seguridad      | Cifrado en tránsito (TLS 1.2+), en reposo (KMS), *secrets manager* |
| Privacidad     | PII redaction configurable por tenant; retención por política      |
| Confiabilidad  | *Retries* exponenciales, *idempotency keys* en ingesta             |
| Mantenibilidad | IaC (Terraform), CI/CD, *runbooks*, *feature flags*                |
| Observabilidad | *Traces*, *metrics*, *logs* centralizados; *SLO dashboards*        |
| Portabilidad   | Soporte nativo AWS/Azure/GCP; imágenes Docker estándar             |

---

## 5. Métricas de calidad (RAG)

* **Retrieval**: recall\@k, nDCG\@k, cobertura por fuente/idioma.
* **Respuesta**: groundedness (citas sustentan), answer‑relevance, *faithfulness*.
* **Operación**: costo por respuesta, latencia por etapa, tasa de reintentos.
* **Negocio**: CSAT, tasa de resolución, ahorro de tiempo.

**Umbrales MVP**: nDCG\@10 ≥ 0.55, groundedness ≥ 0.9, answer‑relevance ≥ 0.8, costo ≤ \$0.005/resp (promedio).

---

## 6. Arquitectura (alto nivel)

**Componentes lógicos**

1. **Conectores de ingesta** (HTTP/GDrive/Confluence/SharePoint/S3).
2. **Workers de parsing** (OCR, extracción, normalización, chunking, metadatos).
3. **Lakehouse** (*raw*, *clean*, *features*, *embeddings*, *evals*, *metrics*).
4. **Indexado**:

   * Léxico: Elasticsearch/OpenSearch.
   * Vectorial: Milvus/pgvector/Pinecone (HNSW/IVF).
   * *Reranker* (bge‑reranker / servicio externo).
5. **Orquestación**: LangGraph (flujos condicionales + herramientas).
6. **Serving**: API FastAPI (REST/gRPC), caché Redis, rate limiting.
7. **UI**: Next.js (chat + administración + paneles de calidad).
8. **Observabilidad**: Langfuse/LangSmith + Prometheus/Grafana + Loki.
9. **Evaluación**: jobs Ragas + *golden set* + *replay* de queries.
10. **Auto‑tuning**: Airflow/Prefect, PRs automáticos con *gates*.

**Flujo de datos (consulta)**
Usuario → API `/v1/chat` → LangGraph: Detect Idioma → Retrieve (BM25+vector, filtros) → Rerank → Grounding → LLM → Verificador de citas → Postproceso (políticas) → Respuesta con citas → Observabilidad (trazas/métricas).

**Flujo de datos (ingesta)**
Scheduler/Webhook → Cola `ingest.requests` → Worker: fetch → OCR/extract → clean → chunk → embed → write lakehouse → update índices (léxico + vector) → publicar `ingest.results`.

---

## 7. Topologías por nube (referencia)

**AWS**: S3 (lake) + Glue/Lambda/SQS + OpenSearch + RDS‑PG/pgvector o Milvus on ECS/EKS + Bedrock/OpenAI + API GW + EKS + Prometheus/Grafana/Loki + KMS + Secrets Manager.

**Azure**: ADLS + Data Factory/Functions + Azure AI Search (opción léxica+semántica) + Cosmos DB/PG + Azure OpenAI + AKS + Monitor/AppInsights + Key Vault.

**GCP**: GCS + Cloud Run/Cloud Functions + Elastic (managed) o OpenSearch + AlloyDB/pgvector o Vertex Vector Search + Vertex AI (LLM/ReRank) + GKE + Cloud Monitoring + KMS/Secret Manager.

---

## 8. Modelo de datos (esquemas simplificados)

**Documento (raw/clean)**

```json
{
  "id": "doc_123",
  "tenant_id": "acme",
  "source": "gdrive",
  "path": "folders/handbook.pdf",
  "mime": "application/pdf",
  "title": "Employee Handbook",
  "language": "es",
  "created_at": "2024-10-12T10:00:00Z",
  "updated_at": "2025-01-01T10:00:00Z",
  "version": 3,
  "hash": "sha256:...",
  "acl": ["group://hr", "user://ana"],
  "pii_tags": ["email", "phone"]
}
```

**Chunk/Embedding**

```json
{
  "id": "doc_123#p5_c2",
  "tenant_id": "acme",
  "doc_id": "doc_123",
  "chunk_id": 2,
  "text": "Política de vacaciones...",
  "tokens": 128,
  "embedding_vector_id": "vec_abc",
  "metadata": {"page": 5, "section": "2.1", "date": "2025-01-01"}
}
```

---

## 9. API (contratos resumidos)

**POST `/v1/chat`**
Req:

```json
{
  "tenant_id": "acme",
  "query": "¿Cuál es la política de vacaciones?",
  "filters": {"date_from": "2024-01-01", "type": ["policy"]},
  "top_k": 8,
  "rerank": true
}
```

Resp:

```json
{
  "answer": "La política establece...",
  "citations": [
    {"doc_id": "doc_123", "page": 5, "score": 0.82, "snippet": "La política..."}
  ],
  "metrics": {"latency_ms": 780, "tokens_prompt": 850, "tokens_output": 120}
}
```

**POST `/v1/docs/ingest`**

* Sube o registra una fuente; devuelve `job_id` y avanza por cola.

**GET `/v1/metrics`**

* Métricas agregadas por tenant (latencia, costos, recall\@k si hay eval activa).

---

## 10. Seguridad

* **Auth**: OAuth2/OIDC → JWT (scopes/roles), *token exchange* para API.
* **RBAC**: admin/editor/viewer/auditor.
* **Aislamiento**: índices/buckets/espacios de nombres por tenant; claves KMS por tenant; *network policies* en K8s.
* **DLP/PII**: redacción en ingesta; *content firewall* (bloquea instrucciones embebidas en docs).
* **Auditoría**: logs inmutables de acceso y consulta; retención configurable.

---

## 11. Observabilidad

* **Traces**: spans para retrieve, rerank, llm; *sampling* por tasa/costo.
* **Métricas**: p50/p95/p99, QPS, errores, costos, `cache_hit`, `rerank_gain`.
* **Logs**: structured, correlacionados por `trace_id`.
* **Dashboards**: por tenant y global; SLOs; alertas (Pager/On-call).

---

## 12. Auto‑tuning y evaluación

* **Datasets**: *golden set* ≥ 200 Q/A por tenant (cuando aplique) + *replay* anonimizado.
* **A/B**: prompts, modelos, parámetros de índice, `k`, reranker.
* **Jobs**: nocturnos (Airflow/Prefect) → escribe métricas → si mejora ≥ 2–3% en *gated KPIs*, crea PR con cambios en `configs/`.

---

## 13. Operación y DevOps

* **CI/CD**: lint + tests + *eval‑CI* (Ragas) + seguridad (SAST/DAST) + despliegue azul/verde.
* **IaC**: Terraform para nube; Helm/Kustomize para K8s; *secrets manager*.
* **Backups/DR**: snapshots diarios de índices + lakehouse; RTO 1h, RPO 15m.
* **Feature flags**: *kill‑switch* para modelos costosos/rerankers.

---

## 14. Roadmap (MVP → v1)

1. **MVP (Semanas 1‑4)**: HTTP/GDrive, lake local (DuckDB/Delta), OpenSearch + pgvector, LangGraph, FastAPI, UI básica, Langfuse, mini *golden set*.
2. **v0.9 (Semanas 5‑8)**: Reranker, filtros metadatos, RBAC, panel de calidad, caching, métricas de costo, SLO dashboard.
3. **v1.0 (Semanas 9‑12)**: Multi‑tenant fuerte (namespaces/KMS), auto‑tuning nocturno con PRs, DR/backup, demo pública.

---

## 15. Riesgos y mitigaciones

* **Prompt‑injection/Data exfiltration** → *content firewall*, verificador de citas, *allow‑list* de herramientas.
* **Drift de calidad** → *eval‑CI*, *replay* periódico, alertas por caída de métricas.
* **Costos impredecibles** → presupuestos, *rate limiting*, caching, límites de contexto.
* **Latencias altas** → tuning de índices (HNSW), warm pools de modelos, gRPC, compresión de embeddings.

---

## 16. Criterios de aceptación (extracto)

* **CA‑1**: Consulta de 1 oración devuelve respuesta con ≥2 citas válidas y latencia p95 ≤ 1.2s en set de 100 preguntas.
* **CA‑2**: Ingesta de 1k PDFs (≤20MB c/u) finaliza en < 2h con ≥ 99% éxito y *retries* documentados.
* **CA‑3**: Panel muestra nDCG\@10, groundedness y latencia por tenant con actualización ≤ 5 min.
* **CA‑4**: Aislamiento por tenant validado: usuario de `acme` no puede consultar docs de `globex`.
* **CA‑5**: Auto‑tuning genera PR con cambios de `k`/prompt si mejora KPI ≥ 2% en *golden set*.

---

## 17. Anexos (referencias internas)

* Especificaciones de endpoints detalladas.
* Esquemas de índices y *mappings* para OpenSearch.
* Configs de HNSW/IVF sugeridas (por tamaño y distribución del corpus).
* Guías de *chunking* por tipo de documento.
* Plantillas de *runbooks* (on‑call, incident management).
