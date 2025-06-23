Hola 👋
Si estás leyendo esto, significa que te di un trocito de mi máquina, espero que te sirva para cualquier proyecto que tengas por ahí.
Recuerda que el propósito de esta máquina es aprender y crecer juntos, nada de lo que hagas aquí va a ser privado.
Espero no tener que recordarlo, pero está estrictamente prohibido utilizar esta máquina para temas ilegales o poco éticos que me puedan poner en un aprieto.

Te dejo un pequeño proyecto de prueba de Docker compose (usa podman, pero la compatibilidad es del 90%)
> docker compose up -d

Para probar que sí funcione (debido a que no puedes acceder desde afuera), puedes usar
> curl localhost

Puedes acceder desde el exterior instalando túneles de Cloudflare (preinstalado)
> cloudflared tunnel --url http://localhost:80 &

Mas detalles:
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

Un saludo.
---

Hello 👋
If you're reading this, it means I've given you a piece of my machine. I hope it helps you with any projects you have going on.
Remember, the purpose of this machine is to learn and grow together; nothing you do here will be private.
I hope I don't have to remind you, but using this machine for illegal or unethical purposes that could put me in trouble is strictly prohibited.

Here's a small Docker Compose test project (it uses Podman, but compatibility is 90%).
> docker compose up -d

To test that it does work (because you can't access it from outside), you can use
> curl localhost

You can access from outside installing cloudflare tunnels (preinstalled)
> cloudflared tunnel --url http://localhost:80 &

More details:
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

Best regards.
