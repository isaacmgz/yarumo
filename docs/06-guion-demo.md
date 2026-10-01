# 06 · Guion de la demo (5 minutos)

## Antes de empezar (checklist, 15 min antes)

- [ ] PC-A conectado a corriente, `podman compose ps` con los 5 servicios arriba.
- [ ] `./scripts/check-stack.sh` en verde (HA, MQTT, Savi, Ollama, simulador).
- [ ] `./scripts/demo-reset.sh`: casa vacía de dispositivos encendidos, historia sembrada (`seed=42`), sugerencias en estado `nueva` salvo R1 (plancha) ya `activa`, contador de ahorro en cero, selects de presencia en `auto`.
- [ ] Mensaje de prueba al chat para "calentar" el modelo (la primera respuesta es la más lenta).
- [ ] PC-B con el dashboard "Yarumo" en pantalla completa.
- [ ] Ambos celulares con Wi-Fi de la casa, app abierta una vez, batería > 50 %, sin modo ahorro.
- [ ] `input_number.retardo_casa_vacia_s` en 30.
- [ ] Escenario inicial: `POST /escenarios/manana_laboral` (la casa "despierta").

## Paso a paso

| # | Tiempo | Qué se hace | Qué se dice (idea, no libreto) | Plan B |
|---|---|---|---|---|
| 1 | 0:00–0:40 | Mostrar el panel: dos residentes en casa, consumo actual, luces y equipos encendidos | "Este es un apartamento como los de cualquier barrio de estrato 3. Todo lo que ven corre en este portátil, sin nube." | — |
| 2 | 0:40–1:40 | Abrir Savi en el panel. Mostrar la sugerencia D1 con su evidencia | "Savi revisó tres semanas de rutina (simuladas para esta demo) y notó algo: casi siempre que salimos, la TV y el PC se quedan prendidos." | Si la explicación del LLM tarda, la tarjeta ya tiene el texto de plantilla |
| 3 | 1:40–2:10 | Llega la notificación al celular: "¿Quieres que lo automatice?" → tocar **Sí** | "La casa propone; nosotros decidimos." | Aprobar desde el panel |
| 4 | 2:10–3:10 | Escenario `olvido_salida`. En el Android, apagar la Wi-Fi; el iPhone en `fuera` desde el panel. A los ~30 s la casa queda vacía, se apagan TV y PC, llega el aviso y el contador empieza a correr | "Nos fuimos y dejamos todo prendido, como siempre. Esta vez la casa se dio cuenta." | Si el Android tarda > 45 s, poner su select en `fuera` |
| 5 | 3:10–3:50 | Escenario `plancha_olvidada` con la casa vacía → se apaga al instante, alerta de prioridad | "Esta no la aprendió: es seguridad, viene de fábrica." | — |
| 6 | 3:50–4:30 | Desconectar el cable WAN del router (o apagar los datos del router). Preguntar en el chat: "¿Por qué apagaste la TV?" y "¿De dónde sale ese número?" | "Se fue el internet y la casa sigue pensando. Y nos dice de dónde salen sus números." | Si el LLM no responde, mostrar la sección "¿cómo se calcula?" del panel |
| 7 | 4:30–5:00 | Volver el Android a la Wi-Fi: la casa detecta el regreso, cierra el conteo y muestra el ahorro de la ausencia y el proyectado del mes | "Tu casa aprende tus rutinas y deja de gastar energía cuando nadie la está usando." | — |

## Frases que NO se dicen

- Cifras de ahorro que no estén en pantalla.
- "La IA aprendió sola con machine learning": aprendió con reglas estadísticas explicables, y eso se dice con orgullo.
- Que es un producto terminado o que ya tiene clientes.
- Que la historia de tres semanas es real.

## Grabación para video

- Grabar la pantalla de PC-B (OBS) y, en paralelo, el celular con su propia grabación de pantalla.
- Hacer dos tomas completas; usar el plan B sin cortar si algo falla, porque también demuestra robustez.
- Para el video, el paso 4 puede acortarse con `retardo_casa_vacia_s = 10`.
