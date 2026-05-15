# Architecture

Detailed diagrams of the AI Changelog Generator internals.

## Component overview

```mermaid
graph LR
  env["Environment Variables"] --> config["config.py<br/>Config.from_env()"]
  config --> gen["generate.py<br/>Orchestrator"]

  gen --> gh_client["github_client.py<br/>REST API Client"]
  gh_client --> gh_api["GitHub API"]

  gen --> classifier["classifier.py<br/>Heuristic Classifier"]

  gen --> prompt["prompt.py<br/>Prompt Builder"]
  prompt --> providers["providers.py<br/>LLM Fallback Chain"]
  providers --> llm_apis["LLM APIs<br/>Groq / Gemini / Anthropic / OpenAI"]

  gen --> evaluator["evaluator.py<br/>Self-Evaluation Loop"]
  evaluator --> providers

  gen --> publisher["publisher.py<br/>Release Publisher"]
  publisher --> gh_client

  classDef core fill:#2563eb,stroke:#1d4ed8,color:#fff
  classDef data fill:#d97706,stroke:#b45309,color:#fff
  classDef ext fill:#6b7280,stroke:#4b5563,color:#fff
  classDef engine fill:#059669,stroke:#047857,color:#fff

  class config,gen core
  class gh_client,classifier data
  class prompt,providers,evaluator engine
  class env,gh_api,llm_apis,publisher ext
```

**Legend:** blue = core orchestration, amber = data access/classification, green = LLM engine, grey = external systems.

## Pipeline sequence

End-to-end flow from GitHub Action trigger to published changelog.

```mermaid
sequenceDiagram
  participant action as GitHub Action
  participant gen as generate.py
  participant config as Config
  participant gh as GitHubClient
  participant cls as Classifier
  participant prompt as PromptBuilder
  participant llm as LLM Providers
  participant eval as Evaluator
  participant pub as Publisher

  action->>gen: Trigger on release

  gen->>config: from_env()
  config-->>gen: Config object

  gen->>gh: get_previous_tag(tag)
  gh-->>gen: previous tag

  gen->>gh: get_commits_between(prev, current)
  gh-->>gen: commits list

  gen->>gh: get_merged_prs(prev, current)
  gh-->>gen: PR list

  gen->>cls: classify(commits, prs)
  cls-->>gen: ClassifiedChanges

  gen->>prompt: build_generation_prompt(classified)
  prompt-->>gen: user prompt

  gen->>llm: call_llm_with_fallback(chain, prompt)
  llm-->>gen: changelog body

  opt max_eval_retries > 0
    gen->>eval: evaluate_and_refine(body, chain)
    eval->>llm: evaluation request
    llm-->>eval: JSON verdict
    eval-->>gen: refined body
  end

  gen->>pub: publish(body, tag)
  pub->>gh: update_release_body(id, body)
  gh-->>pub: 200 OK

  opt update_changelog_file
    pub->>gh: update_file_contents(CHANGELOG.md)
    gh-->>pub: committed
  end

  pub-->>gen: done
```

## Provider fallback chain

How `call_llm_with_fallback` handles errors across providers. Each provider gets up to 3 retries on 5xx. Rate limits (429) and auth errors skip immediately to the next provider.

```mermaid
graph TD
  start_node(["Start: provider chain"]) --> next_prov{"Next provider<br/>available?"}

  next_prov -->|"Yes"| call_api["Call provider API"]
  next_prov -->|"No"| all_fail["Raise LLMError<br/>ALL_PROVIDERS_FAILED"]

  call_api --> check_resp{"Response<br/>status?"}

  check_resp -->|"2xx"| check_trunc{"Output<br/>truncated?"}
  check_trunc -->|"No"| success(["Return changelog"])
  check_trunc -->|"Yes"| warn_trunc["Log truncation warning"] --> success

  check_resp -->|"429"| skip_rate["Log: rate limited"] --> next_prov
  check_resp -->|"401 / 403"| skip_auth["Log: auth error"] --> next_prov

  check_resp -->|"5xx"| retry_check{"Retries<br/>left?"}
  retry_check -->|"Yes"| backoff["Wait 2^N seconds"] --> call_api
  retry_check -->|"No"| skip_5xx["Log: server error"] --> next_prov

  check_resp -->|"Empty"| skip_empty["Log: empty response"] --> next_prov

  classDef core fill:#2563eb,stroke:#1d4ed8,color:#fff
  classDef data fill:#d97706,stroke:#b45309,color:#fff
  classDef ext fill:#6b7280,stroke:#4b5563,color:#fff
  classDef engine fill:#059669,stroke:#047857,color:#fff

  class start_node,call_api,check_resp core
  class success engine
  class all_fail ext
  class skip_rate,skip_auth,skip_5xx,skip_empty,warn_trunc data
```

## Self-evaluation loop

The evaluator never blocks publishing. Every failure path returns the best available changelog body.

```mermaid
graph TD
  start_node(["Receive changelog body"]) --> build_eval["Build evaluation prompt"]
  build_eval --> call_llm["Call LLM for evaluation"]

  call_llm --> llm_fail{"LLM call<br/>failed?"}
  llm_fail -->|"Yes"| safe_return_1(["Return current body<br/>fail-safe"])

  llm_fail -->|"No"| parse_json["Parse JSON response"]
  parse_json --> parse_fail{"Parse<br/>error?"}
  parse_fail -->|"Yes"| safe_return_2(["Return current body<br/>default ok=true"])

  parse_fail -->|"No"| check_ok{"Evaluation<br/>ok?"}
  check_ok -->|"Yes"| return_ok(["Return changelog"])

  check_ok -->|"No"| retries_left{"Retries<br/>left?"}
  retries_left -->|"No"| safe_return_3(["Return last body<br/>max retries hit"])

  retries_left -->|"Yes"| regen["Regenerate with feedback"]
  regen --> regen_fail{"Regeneration<br/>failed?"}
  regen_fail -->|"Yes"| safe_return_4(["Return previous body<br/>fail-safe"])
  regen_fail -->|"No"| build_eval

  classDef core fill:#2563eb,stroke:#1d4ed8,color:#fff
  classDef safe fill:#059669,stroke:#047857,color:#fff
  classDef warn fill:#d97706,stroke:#b45309,color:#fff

  class start_node,build_eval,call_llm,parse_json,regen core
  class return_ok,safe_return_1,safe_return_2,safe_return_3,safe_return_4 safe
  class check_ok,retries_left,llm_fail,parse_fail,regen_fail warn
```

**Legend:** blue = processing steps, green = exit points (all return a changelog), amber = decision points.
