# Investigacion RAG sobre una reunion (2026-10-17)
Marca: [V]=verificado en fuente citada, [E]=estimacion mia, sin medir, [?]=no verificado.

## Diseno recomendado: "el LLM elige, el codigo cita"
Garantia de literalidad por construccion: el LLM NUNCA escribe citas; solo devuelve IDs de segmento. El codigo copia el texto literal del segmento y arma "Se dijo que «<cita literal>» [mm:ss]".
1. Indice (una vez por reunion): BM25 (`bm25s`, tokenizado es + sin stopwords, stemming snowball es opcional) + embeddings densos. Segmentos ~15 s; ventanas de 1 segmento + vecinos al mostrar contexto. OCR en el mismo indice con tipo "pantalla" y timestamp del frame.
2. Embeddings: opcion A `intfloat/multilingual-e5-small` (118M, ~470 MB fp32; prefijos "query: "/"passage: "). MIRACL-es nDCG@10 ~50.8 [V, tabla Granite arXiv 2502.20204, columna inferida]. Opcion B `google/embeddinggemma-300m` (308M, ctx 2048, MTEB-Multi v2 61.15; Q4_0 60.62, casi sin perdida) [V, HF card]. Opcion C `Qwen/Qwen3-Embedding-0.6B` (0.6B, MTEB-Multi 64.33, prompt "Instruct: ...\nQuery:") [V, HF card]; GGUF via llama-server --embedding [?]. BGE-M3 (568M) ~59.2 MIRACL-es [V parcial, mGTE arXiv 2407.19669, columna inferida] pero mas pesado. Recomendacion: empezar con e5-small (rapido, suficiente en un solo documento de 800 segmentos); subir a EmbeddingGemma Q4/Qwen3-Emb-0.6B solo si la evaluacion propia (eval/) muestra recall@10 insuficiente. granite-embedding-small multilingual y jina v3: no verificados [?].
3. Fusion: RRF (k=60) de top-30 BM25 y top-30 denso -> top-20. Barato (<10 ms). Expansion de consulta barata sin LLM: variantes morfologicas/stemming, sinonimos del propio glosario de la reunion, cifras escritas en letra y digitos ("1843"); evitar expansion con LLM (12 tok/s).
4. Reranker (opcional, medir antes): `BAAI/bge-reranker-v2-m3` (~568M) o Qwen3-Reranker-0.6B; GGUF de Qwen3-Reranker en llama.cpp requiere rama/fix no fusionado segun READMEs de comunidad [V, HF cicaba/Qwen3-Reranker-0.6B-GGUF-llamacpp-fixed, puede estar ya resuelto]. Latencia CPU de 20 pares: sin cifras publicas encontradas [?]; estimo 3-10 s para 0.6B [E]. Con una sola reunion, el reranker probablemente no compensa; usar el propio LLM como filtro (paso 5).
5. Seleccion con LLM (Qwen3.5-4B, thinking desactivado): prompt = instruccion corta + top-8..10 segmentos "[id] mm:ss texto" (~400-600 tokens) + pregunta. Salida restringida con GBNF a `ids ::= "[" id ("," id)* "]" | "NINGUNO"` con `id` = alternativas literales de los IDs recuperados (la "copy mechanism" a nivel de ID, trivial de generar dinamicamente). max_tokens ~40. Para granularidad fina: segmentos ya cortos (15 s); si hace falta subfrase, el codigo resalta la frase con mayor solape lexico con la pregunta, no el LLM.
6. Verificacion determinista: cada cita es substring exacto del segmento (assert). Comprobar que terminos clave de la pregunta (numeros, nombres, colores) aparecen en el segmento citado; si no, descartar el ID. Anti "femenino->rosa": no hay parafrasis, solo cita literal. Opcional: NLI multilingue pequeno (p.ej. mDeBERTa-xnli) para filtrar segmentos que no responden [?, no evaluado].
7. "No se menciona": si LLM devuelve NINGUNO o el score de recuperacion maximo (BM25 normalizado y coseno) esta bajo umbral calibrado en eval/, responder "No se menciona" sin llamar al LLM.
8. Respuesta 0 (instantanea, sin LLM): al terminar la recuperacion (<1 s) mostrar top-5 segmentos con timestamp y terminos resaltados, etiquetados "candidatos". Luego el LLM filtra/ordena y la UI marca cuales responden (streaming de IDs: cada ID aparece al generarse).

## Presupuesto de latencia en ProBook [E salvo prompt/gen dados por el usuario]
- Indexado (una vez): e5-small ~800 segmentos de ~40 tokens; CPU 4C, ~20-60 s [E]; BM25 <1 s. EmbeddingGemma/Qwen3-0.6B: 2-5x mas [E].
- Consulta: embedding ~50-150 ms; BM25+RRF <20 ms.
- Prefill LLM: ~700 tokens / 43 tok/s ~ 16 s (instruccion 200 + 9 segmentos x 45 + pregunta).
- Generacion: ~30 tokens / 12 tok/s ~ 2.5 s (solo IDs).
- Total ~20 s; primer resultado util (Respuesta 0) <1 s; primer ID del LLM ~17 s. Margen amplio bajo 60 s; si se quisiera redactar prosa, 150 tokens = +12 s.

## Trucos de latencia, ordenados por rentabilidad
1. Contexto minimo (top 6-10 segmentos) + salida solo IDs: es el ahorro principal (prefill domina). [E]
2. Thinking de Qwen3.5 desactivado (chat_template_kwargs enable_thinking=false) o la latencia se multiplica. [E]
3. Respuesta extractiva inmediata + refinamiento LLM en streaming.
4. Servidor caliente, modelo residente (mlock/--no-mmap), `--parallel 1`, hilos = nucleos fisicos (README actas ya lo mide).
5. Cache de prefijo: poco valioso aqui (la instruccion fija son ~200 tokens ~ 5 s). En Qwen3.5 (hibrido/recurrente) el reuso depende de checkpoints (`--ctx-checkpoints`, `--checkpoint-every-n-tokens`) y es fragil: con chunks RAG variables llama.cpp descarta checkpoints y reprocesa todo [V, issue #24587, cerrado "not planned" 2026-08-01]; hubo un fix de restore para hibridos [?, solo V2EX]. Poner la instruccion fija al principio, medir en el build en uso, no depender de ello. Slot save/restore: solo util para cachear el prefijo fijo; no para segmentos.
6. KV precomputado por segmento: inviable (KV posicional y estado recurrente dependen del prefijo) [E, razonamiento].
7. Cache de resultados por pregunta normalizada en work/<hash>/.
8. Reranker cross-encoder solo si eval/ demuestra ganancia.

## Literatura (generacion atribuida)
- FRONT (arXiv 2408.04568): extraer citas fundamentadas primero y condicionar la respuesta; requiere fine-tuning [V].
- Quote-Tuning (NAACL 2025, arXiv 2404.03862): citas verbatim, pero de datos de preentrenamiento, no del contexto [V].
- HAGRID (arXiv 2307.16883): respuestas atribuibles tienden a ser extractivas; mas citas en contexto degradan atribucion [V].
- Pedir citas literales y comprobarlas como substring del original como detector de alucinacion (practica, post de Lifen) [V, no peer-review].
- Decodificacion con gramatica dinamica restringida a substrings del contexto: no encontre trabajo especifico [?]; GBNF de llama.cpp lo permite en principio (gramatica generada por consulta) [V docs GBNF, uso mio = inferencia]. Gramatica a nivel de substring con ~10 segmentos es pesada para el sampler; por eso ID-level.
- Prompting es "estilo indirecto": plantilla fija en codigo ("Se dijo que «...»"), no en el LLM.

## Ejemplos open source
- Quorum (MCP/FastAPI offline, QA sobre reuniones con speaker+timestamp y rechazo cuando no hay soporte) [V solo listado glama.ai, licencia/repo no vistos].
- PinRAG (PyPI): citas con pagina/timestamp YouTube [V listado].
- "AI Video Assistant with RAG" (Streamlit+ChromaDB+Whisper local) [V solo descripcion].
Nada maduro que copiar; la idea reutilizable es la de Quorum: rechazar si no hay soporte.

## Riesgos
- Recuperacion falla con vocabulario distinto (ASR errores, sinonimos): "No se menciona" falso. Mitigar: hibrido, umbral conservador, mostrar candidatos aun asi.
- Cita fuera de contexto (segmento relevante pero afirmacion ya negada en el siguiente): mostrar vecinos +-1.
- ASR erroneo se cita literal (es fiel al transcript, no a lo dicho).
- Preguntas de sintesis/agregacion ("cuantas decisiones...") no encajan; responder solo con citas.
- Qwen3.5 puede devolver IDs irrelevantes; el filtro lexico los poda pero reduce recall.
- Numeros de latencia/indexado son estimaciones: medir en el ProBook.
- Cifras de MIRACL-es provienen de tablas con columna inferida; validar con un set propio de ~30 preguntas.
