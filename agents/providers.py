"""Small shared chat client with local-first routing."""
import json
import os
import urllib.request


def chat(config, role_name, messages, temperature=0.2):
    role = config.get("roles", {}).get(role_name, {})
    providers = config["providers"]
    configured = (role.get("provider", "ollama"), role.get("model"))
    # The configured provider/model is the role assignment. Defaults assign local
    # Ollama first and use OpenRouter only as fallback; a deliberate UI override
    # to OpenRouter must remain effective.
    candidates = [configured]
    fallback = role.get("fallback_provider")
    if fallback:
        fallback_route = (fallback, role.get("fallback_model"))
        if fallback_route not in candidates:
            candidates.append(fallback_route)

    last_error = None
    for provider_name, model in candidates:
        if not model or provider_name not in providers:
            continue
        provider = providers[provider_name]
        try:
            if provider_name == "ollama":
                url = provider["base_url"].rstrip("/") + "/api/chat"
                payload = {"model": model, "messages": messages, "stream": False,
                           "options": {"temperature": temperature}}
                headers = {"Content-Type": "application/json"}
            elif provider_name == "openrouter":
                api_key = os.environ.get("OPENROUTER_API_KEY", "")
                if not api_key:
                    last_error = "OPENROUTER_API_KEY is not configured"
                    continue
                url = provider["base_url"].rstrip("/") + "/chat/completions"
                payload = {"model": model, "messages": messages, "temperature": temperature}
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                continue
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.loads(response.read().decode())
            if provider_name == "ollama":
                return result["message"]["content"], provider_name, model
            return result["choices"][0]["message"]["content"], provider_name, model
        except Exception as exc:  # try the configured fallback provider
            last_error = f"{provider_name}/{model}: {exc}"
    raise RuntimeError(f"No configured model could complete the {role_name} request: {last_error}")
