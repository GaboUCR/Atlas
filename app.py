import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# LangChain & amigos
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

load_dotenv()

# --- Configuración de modelos ---
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Falta OPENAI_API_KEY en tu entorno o .env")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# --- Base de conocimiento mínima (3 fragmentos de ejemplo) ---
texts = [
    "Manual de soporte (router): Para reiniciar el router, apaga el dispositivo, espera 30 segundos y vuelve a encenderlo. "
    "Si no hay internet en 2 minutos, verifica luces de WAN y reinicia el módem.",
    "WiFi (cambio de contraseña): Ingresa al panel en http://192.168.0.1, inicia sesión como admin, ve a 'Wireless' > 'Security', "
    "cambia la contraseña y guarda. Reinicia la red para aplicar cambios.",
    "Escalamiento de incidencias críticas: Si la conexión cae en producción, registra ticket P1 y contacta al on-call. "
    "Incluye hora del incidente, equipos afectados y pasos ya probados."
]
metadatas = [
    {"source": "manual_router.txt"},
    {"source": "wifi_password.txt"},
    {"source": "escalamiento_ops.txt"},
]

persist_dir = "chroma_db"
vectorstore = Chroma(
    collection_name="kb_demo",   # <- nombre válido (antes: "kb")
    embedding_function=embeddings,
    persist_directory=persist_dir,
)

# Evita reinsertar si ya existe el índice
is_empty = not os.path.exists(persist_dir) or not os.listdir(persist_dir)
if is_empty:
    vectorstore.add_texts(texts=texts, metadatas=metadatas)

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

def format_docs(docs):
    return "\n\n".join([f"- {d.page_content}" for d in docs])

prompt = ChatPromptTemplate.from_template(
    """Eres un asistente técnico. Usa EXCLUSIVAMENTE el CONTEXTO para responder en español.
Si no está en el contexto, responde: "No encuentro esa información en la base".

CONTEXTO:
{context}

PREGUNTA:
{question}

RESPUESTA (clara y en pasos si aplica):"""
)

rag_chain = (
    {"context": retriever | RunnableLambda(format_docs), "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

app = FastAPI(title="Demo RAG Hola Mundo")

class AskRequest(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask")
def ask(req: AskRequest):
    try:
        answer = rag_chain.invoke(req.question, config={"run_name": "RAG-ask"})
        # Recupera fuentes para mostrarlas en la respuesta
        docs = retriever.get_relevant_documents(req.question)
        sources = [
            {"source": (d.metadata or {}).get("source", f"fragmento_{i+1}"),
             "snippet": d.page_content[:200] + ("..." if len(d.page_content) > 200 else "")}
            for i, d in enumerate(docs)
        ]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
