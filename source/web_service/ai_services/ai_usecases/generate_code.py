from internal_config.models import Config
from .utils import _get_openai_client

PROJECT_GENERATION_PROMPT = """
Your task is to create a minimum viable product (MVP) application that achieves the following objectives:

<objective>
{objectives}
</objective>

As aditional:
The target SO is debian, so be careful with details like "python" instad "python3", for example.

Instructions (process you must follow):

1. Plan and structure your approach: Think carefully about how you will write the required code. Document and explain your reasoning.
2. Write the code: Implement the solution as normal, and explain what you are doing.
3. Review your code: Analyze potential issues and risks in your implementation. Document this review.
4. Iterate if needed: If problems are found, go back to step 1 and refine your approach.
5. Follow the steps in order: You must complete at least one full cycle of steps 1–4 before moving forward. Skipping directly to step 6 is not allowed.
6. Finalize and export: Once you are confident the code works, finish with `---HERE-YAML--` and then immediately output the complete project in YAML format, structured like this:

<example>
...
ports:
    - "8080:8080"
environment:
    - PORT=8080

---HERE-YAML--

project: bottle-demo
description: "Pequeño servidor web con Bottle, HTML, Dockerfile y Docker Compose"
files:
  - path: app/main.py
    mode: "0644"
    text: |-
      import os
      from bottle import Bottle, static_file, template

      app = Bottle()

      from bottle import TEMPLATE_PATH
      TEMPLATE_PATH.insert(0, os.path.join(os.path.dirname(__file__), "..", "templates"))

      STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

      @app.route("/")
      def index():
          return template("index", name="Bottle Demo")

      @app.route("/static/<filepath:path>")
      def server_static(filepath):
          return static_file(filepath, root=STATIC_DIR)

      if __name__ == "__main__":
          port = int(os.getenv("PORT", "8080"))
          app.run(host="0.0.0.0", port=port, debug=True, reloader=False)

  - path: templates/index.tpl
    mode: "0644"
    text: |-
      <!doctype html>
      <html lang="es">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>{{name}}</title>
        </head>
        <body>
          <main>
            <h1>{{name}}</h1>
            <p>¡Hola desde Bottle dentro de Docker! 🚀</p>
            <p>Hora del servidor: {{!import time; time.strftime('%Y-%m-%d %H:%M:%S')}}</p>
            <p><a href="https://bottlepy.org/docs/dev/">Docs de Bottle</a></p>
          </main>
        </body>
      </html>

  - path: requirements.txt
    mode: "0644"
    text: |-
      bottle

  - path: Dockerfile
    mode: "0644"
    text: |-
      FROM python:3.12-slim

      ENV PYTHONDONTWRITEBYTECODE=1 \
          PYTHONUNBUFFERED=1

      WORKDIR /app

      RUN apt-get update && apt-get install -y --no-install-recommends \
          ca-certificates \
          && rm -rf /var/lib/apt/lists/*

      COPY requirements.txt ./requirements.txt
      RUN pip install --no-cache-dir -r requirements.txt

      # Copiar el resto del proyecto
      COPY . .

      EXPOSE 8080

      CMD ["python", "app/main.py"]

  - path: docker-compose.yml
    mode: "0644"
    text: |-
      services:
        web:
          build: .
          container_name: bottle-demo
          ports:
            - "8080:8080"
          environment:
            - PORT=8080

  - path: readme.txt
    mode: "0644"
    text: |-
      Este es un simple proyecto que usa bottle y esta dockerizado

  - path: config.json
    mode: "0644"
    text: |-
      {"run": "docker compose down ; docker compose up -d --build"}
</example>

Additional notes:

* Notice that the files `readme.txt` and `config.json` must always be included, especially `config.json`, which should contain the `"run"` field with the command needed to run the project.
* The project does not need to be dockerized unless the objective explicitly requires it.
* After the `---HERE-YAML--` separator, do not write anything except the YAML file.
* Also, the here Yaml should be clear, not ** or any shit like that, the YAML code should not have fences (```) either.
* Also not titles or anything diferent than yaml after the ---HERE-YAML--
* If you want to explain something or add comments, place them in `readme.txt` or before the `---HERE-YAML--`, never after.
"""


def get_project_response(prompt: str):
    """
    Get a response from the OpenAI API using the provided prompt.
    """
    open_ai_data = Config.get_config_values(
        ["openai_api_key", "openai_api_url", "openai_model"]
    )

    openai = _get_openai_client(open_ai_data)
    openai_model: str = open_ai_data.get("openai_model") or "gpt-4"

    prompt_prepared = PROJECT_GENERATION_PROMPT.replace("{objectives}", prompt)

    response = openai.chat.completions.create(
        messages=[{"role": "system", "content": prompt_prepared}],
        model=openai_model,
        stream=False,
    )

    return response.choices[0].message.content
