# Ausgangslage
Wir haben uns gefragt, wie wir sozialwissenschaftliche Interviews effizient gestalten können, indem wir für eine große Gruppe von Interviewees den Ablauf automatisieren können. Unser Fokus liegt auf Migrationsforschung.

## Llama 3.1 lokal verwenden

Die Anwendung verwendet standardmäßig Llama 3.1 8B über Ollamas OpenAI-kompatible API. Installieren und starten Sie [Ollama](https://ollama.com/), installieren Sie den Python-API-Client und laden Sie das Modell:

```powershell
python -m pip install openai
ollama pull llama3.1:8b
```

Installieren Sie außerdem das Python-Paket `openai`, das der API-Client benötigt. Die Verbindung erwartet Ollama unter `http://localhost:11434/v1/`; das Timeout beträgt standardmäßig 180 Sekunden, damit auch das erste Laden des lokalen Modells Zeit hat. `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` und `LLM_TIMEOUT_SECONDS` können bei Bedarf über Umgebungsvariablen überschrieben werden. Für den Mock-Modus setzen Sie `LLM_PROVIDER=mock`.
