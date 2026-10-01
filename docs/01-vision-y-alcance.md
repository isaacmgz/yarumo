# 01 · Visión y alcance

## La idea en una frase

Una casa virtual de estrato 3 donde **Savi aprende la rutina de los residentes, propone apagar lo que se queda prendido cuando no hay nadie, y muestra cuánto se ahorró**. Todo corre local, sin hardware domótico, con los computadores y celulares que ya tenemos.

## Qué debe demostrar (en orden de importancia)

1. **Aprende y propone.** A partir de un historial de rutina, Savi detecta un patrón ("entre semana, cuando ambos salen, la TV y el PC del estudio quedan encendidos") y lo explica en lenguaje natural con la evidencia.
2. **El humano decide.** La sugerencia se aprueba con un toque (desde el celular o el panel). Solo entonces se crea la automatización en Home Assistant.
3. **Actúa.** Cuando la casa queda vacía, la automatización apaga lo que corresponde y avisa al celular.
4. **Cuantifica.** Un contador muestra la energía evitada (kWh) y su valor estimado en pesos, con el cálculo visible.
5. **Funciona sin internet.** Al desconectar el internet del router, la casa y Savi siguen funcionando.

## La casa virtual

Apartamento de 3 habitaciones: sala-comedor, cocina, habitación principal, habitación 2 y estudio. Dos residentes, cada uno representado por un celular real:

| Residente | Celular | Rol en la demo |
|---|---|---|
| `residente_1` | Android | Presencia y notificaciones accionables; se "va de casa" en vivo |
| `residente_2` | iPhone | Presencia y notificaciones |

Si un celular falla en vivo, el modo demo permite forzar la presencia desde el panel (ver `04-home-assistant.md`).

## Alcance del MVP

Dentro:

- Simulador de 9 dispositivos y 7 sensores por MQTT, con potencia y energía (ver `03-contrato-mqtt.md`).
- Home Assistant con presencia de 2 residentes, dashboard "Yarumo" y panel de Energía.
- Savi: ingesta de eventos, 3 detectores de patrones, sugerencias con evidencia, aprobación, creación de automatizaciones, contador de ahorro y chat en español con LLM local.
- Siembra de 21 días de rutina sintética, etiquetada como tal.
- Guion de demo de 5 minutos con plan B.

Fuera (por ahora):

- Hardware real (Zigbee, Matter, enchufes medidores). Llega en el Bloque 1.
- Control por voz (Whisper/Piper). Opcional, después del MVP.
- Cámara IP con detección de movimiento. Opcional (hito extra).
- VLAN de IoT real (requiere router administrable).
- Multiusuario, multi-casa, nube, app propia.
- Aprendizaje automático "de verdad" (modelos entrenados). Los detectores son estadísticos y explicables; eso es una ventaja para la demo, no una carencia.

## Por qué así

- **Coherente con la postulación.** Yarumo se presenta con el eslogan del ahorro energético y la categoría de sostenibilidad; la demo prueba exactamente eso.
- **Coherente con el Bloque 0.** Costo cero, sobre hardware existente, produce algo real y reutilizable: cuando lleguen los enchufes reales en 2027, solo se reemplaza `sim-casa` por dispositivos Zigbee con los mismos `entity_id`.
- **Explicable.** Un detector que cuenta "4 de 5 días" se entiende y se audita; un modelo opaco no convence a un jurado ni a un cliente.

## Criterio de éxito de la demo

Una persona que no sabe de domótica entiende en menos de 5 minutos qué aprendió la casa, por qué apagó algo y cuánto se ahorró, y nada de lo que vio era un video pregrabado.
