# Entrevista

Respuestas de Miguel, 2026-11-09. Las preguntas Q10, Q16 y Q20 eran "¿paramos aquí?": las dos primeras fueron "no" y Q20 fue "sí".

| # | Pregunta | Respuesta | ¿La recomendada? |
|---|---|---|---|
| Q1 | ¿Se pueden cambiar las cuentas en un payout concreto? | Selector por cuenta, solo cuentas existentes, sin monedas sueltas. Sustituye a la elección de la Fase 57. | Sí |
| Q2 | ¿Qué pasa con los payouts sin cuenta? | La migración crea una cuenta por moneda ("USD account", "EUR account") y se la asigna. Miguel las renombra después. | Sí |
| Q3 | ¿Cómo se edita un payout y qué pasa con lo no confirmado? | La fila sigue editable, el botón sale solo si algo cambió, y lo no confirmado se queda en el navegador hasta confirmar o limpiar. | Sí |
| Q4 | ¿Sello solo, o sello y monedas? | El sello cae y suelta monedas una sola vez, proporcionales a lo cobrado. | Sí |
| Q5 | ¿Cambiar la cadena afecta a lo guardado? | Cada payout conserva la suya. El cambio afecta solo a los payouts nuevos. | Sí |
| Q6 | ¿Qué hace la X y cómo se borra? | La X limpia ese número, que vuelve a calcularse (la primera cuenta, al importe facturado). Borrar es una acción pequeña en la fila confirmada, con aviso y Undo. | Sí |
| Q7 | Proyecto sin cuentas asignadas | Se elige en la fila. | No, se recomendó "Assign accounts" |
| Q8 | ¿Se quitan "Use" y los selectores Paid from y Paid into? | Se quitan. Sustituye a la elección de la Fase 57. | Sí |
| Q9 | ¿Qué miden el rojo y el DIFF? | Rojo: primera cuenta menos facturado. DIFF: facturado al tipo del día frente a la última cuenta. Los ingresos salen de la última. "= €X set the € value" solo si la última no está en euros. | Sí |
| Q11 | Proyecto sin cuentas: ¿cuántas líneas? | Una línea, y rellena la primera cajita del proyecto. | No, se recomendó no tocar las cajitas |
| Q12 | Reglas de las cajitas | Soltar sobre una ocupada la reemplaza, sin huecos (se corren a la izquierda), sin repetir cuenta en la cadena, X para quitar. | Sí |
| Q13 | Arrastre en el móvil | Mantener pulsado 300 ms con vibración breve y scroll automático. Además, tocar una cajita abre la lista de cuentas, que sirve también para teclado y lectores de pantalla. | Sí |
| Q14 | ¿Qué se reordena? | Cuentas, fuentes y plantillas de día. El orden se respeta en todos los selectores y listas. El asa de puntitos arrastra directamente, sin mantener pulsado. | Sí |
| Q15 | ¿Dónde va el botón? | En el sitio de la insignia PAID OUT. Al confirmar, el sello cae ahí y se convierte en PAID OUT. | Sí |
| Q17 | ¿A qué día se calcula cada salto? | Al domingo de la semana del payout, en todos los saltos. | Sí |
| Q18 | Lo que ya hay en Options, y archivar | "Paid from" pasa a la primera cajita y "Paid into" a la siguiente. Archivar quita la cuenta de las cajitas sin tocar los payouts guardados. | Sí |
| Q19 | ¿Mockup antes de construir? | Sí, un mockup que se pueda probar. | Sí |
| Q21 | ¿Qué hacemos con la entrevista? | Guardarla y escribir un prompt para una conversación nueva. | Sí |

# Riesgos aceptados

- **Q7:** se pueden apuntar payouts en un proyecto sin cadena. Mitigación: la fila ofrece una sola línea, y si no existe ninguna cuenta enlaza a crear una.
- **Q11:** elegir en la fila cambia la configuración del proyecto sin pasar por Options. Mitigación: la primera cajita solo se rellena si estaba vacía, y solo al confirmar el payout.

# Sin resolver

Nada.
