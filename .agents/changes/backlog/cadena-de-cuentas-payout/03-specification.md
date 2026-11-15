# Fase 58: la cadena de cuentas de un payout

## Qué es

Un payout deja de tener dos lados fijos (enviado y llegado) y pasa a ser una cadena de 1 a 4 cuentas, configurada por proyecto freelance. Lo normal será una sola cuenta. El caso de Miguel son dos: Stripe en dólares y luego Deutsche Bank en euros.

## Cómo se comporta un payout

- La fila pinta una línea por cuenta de la cadena del proyecto. Cada línea tiene el símbolo de moneda, el importe, una pequeña X y un selector, solo con cuentas existentes. No hay "As billed" ni monedas sueltas.
- La primera cuenta viene rellena con el importe facturado, convertido a su moneda. Cada cuenta siguiente viene calculada desde la anterior, al tipo del domingo de la semana del payout.
- Un número escrito queda fijo. No lo cambia nada de lo que se escriba en otra cuenta, y manda sobre las cuentas siguientes que no estén fijas.
- La X limpia ese número y vuelve a ser calculado. En la primera cuenta vuelve al importe facturado. La X nunca borra el payout.
- El importe final es el de la última cuenta. De ahí salen los ingresos, los euros por hora y los totales.
- Si la última cuenta no está en euros, sigue la línea "= €X set the € value".
- El rojo es la primera cuenta menos lo facturado, a la altura de la primera línea. El chip DIFF es lo facturado al tipo del día frente a la última cuenta, a la altura de la última línea.

## Confirmar

- Los payouts dejan de guardarse al escribir. Es la única excepción a la regla de autoguardado.
- Cada línea de proyecto tiene su propio botón de confirmar, en el sitio de su insignia. La insignia PAID OUT de la semana aparece cuando todas sus líneas están confirmadas (validado en el mockup, 2026-11-11).
- En una semana sin cobrar el botón está siempre, en outline discreto, para poder confirmar un payout cobrado tal cual se facturó. Pasa a sólido cuando algo cambió. En una fila ya confirmada aparece solo cuando algo cambió.
- La fila confirmada sigue siendo editable. Lo no confirmado se queda en el navegador hasta confirmar o limpiar, de modo que recargar no lo pierde. Una flecha de descartar junto al botón devuelve la fila a lo guardado.
- Al confirmar, el sello de Kronos cae en ese sitio, suelta monedas una sola vez, proporcionales a lo cobrado, y se convierte en la insignia PAID OUT. Con movimiento reducido no hay animación.
- Borrar un payout es una acción pequeña en la fila confirmada, con aviso y Undo.
- "Payouts waiting" en la página Days usa la misma celda y el mismo botón.

## Options, Freelance

- A la derecha del nombre y del ratio de cada proyecto hay 4 cajitas en outline discontinuo, en tono apagado. Su posición es la posición en la cadena.
- Las cuentas de abajo se arrastran a las cajitas. Soltar sobre una ocupada la reemplaza. No hay huecos: las cuentas se corren a la izquierda. Una cuenta no se repite en la misma cadena. Una X en la cajita la quita.
- Una cuenta se arrastra a una cajita por su nombre, y se reordena por su asa de puntitos (validado en el mockup).
- En el móvil se mantiene pulsado 300 ms, con vibración breve y scroll automático al acercarse al borde. El scroll se para mientras haya una cajita bajo el dedo. Tocar una cajita abre la lista de cuentas, que sirve también para teclado y lectores de pantalla.
- Se quitan el selector "Use" de las cuentas y los selectores "Paid from" y "Paid into" de las fuentes.
- Cuentas, fuentes y plantillas de día se reordenan con un asa de puntitos que arrastra directamente, sin mantener pulsado. Ese orden se respeta en todos los selectores y listas.
- Archivar una cuenta la quita de las cajitas y no toca los payouts guardados.

## Proyecto sin cuentas (riesgo aceptado)

La fila ofrece una sola línea con selector. Al confirmar, esa cuenta pasa a la primera cajita si estaba vacía. Si no existe ninguna cuenta, la fila enlaza a crear una.

## Lo que ya existe

- Cada payout guarda su propia cadena, con su importe y si estaba fijo. Cambiar la cadena del proyecto solo afecta a los payouts nuevos.
- Los payouts sin cuenta reciben una cuenta por moneda creada por la migración ("USD account", "EUR account"), que Miguel renombra después.
- Un payout de la Fase 57 pasa a tener dos cuentas, enviado y llegado. Uno anterior, con solo lo llegado, pasa a tener una. Ninguna cifra cambia.
- La Fase 57 permite un lado enviado en una moneda suelta, sin cuenta. Ese lado recibe también la cuenta de su moneda. Si enviado y llegado están en la misma cuenta, el enviado recibe otra cuenta creada de su moneda, porque una cuenta no se repite en una cadena.
- "Paid from" pasa a la primera cajita y "Paid into" a la siguiente. Si coinciden, queda una sola.
- La migración debe funcionar tanto desde lo que hay en PROD como desde v57, porque Miguel puede pulsar PROD antes o después.

## Orden de trabajo propuesto

Cada paso se comprueba antes de empezar el siguiente.

1. **Un mockup que se pueda probar** de las cajitas, el arrastre, una fila de tres cuentas y el sello. Se comprueba cuando Miguel lo valida. No se escribe código de la app antes.
2. **Datos y migración**: la cadena, el orden y las cuentas creadas. La migración solo añade: el payout conserva sus columnas de hoy como las cifras de la última cuenta. La retirada de `role`, de los campos `sent_*` y de "Paid from" y "Paid into" pasa al paso 7, en una segunda migración, para que los tests sigan en verde entre pasos. Se comprueba migrando una copia con payouts de cada época: ninguna cifra se mueve un céntimo.
3. **API**: guardar y leer la cadena, confirmar y borrar, copia de seguridad y restauración, CSV. Se comprueba con tests de valores concretos.
4. **Reordenar** con el asa, en las tres listas. Se comprueba que el orden llega a los selectores.
5. **Cajitas** en Options, con arrastre, móvil y teclado. Se comprueba en 1280, 375 y en el emulador Android.
6. **Celda del payout y confirmar**, en Weeks y en Days, sin autoguardado. Se comprueba con la cascada de 3 y 4 cuentas.
7. **Sello** y limpieza de lo que deje sin uso. Se comprueba con la auditoría de geometría y las capturas.

## Criterios de aceptación

- W45 de Miguel: $2,029.50 facturados, Stripe $999, Deutsche Bank sugiere €894.76 a 1.1165. Rojo -$1,030.50, DIFF -50.8%, ingresos €894.76.
- Cadena de tres cuentas: escribir en la segunda cambia la tercera y no la primera. Escribir en la primera no cambia una segunda fija. La X en la segunda la devuelve a calculada.
- Escribir en una fila no guarda nada ni lanza monedas. Confirmar guarda, sella y lanza monedas una vez. Recargar antes de confirmar conserva lo escrito.
- Dos Confirm seguidos en filas distintas: cada sello y sus monedas terminan, ninguno corta al otro.
- Los payouts existentes de cada época suman lo mismo antes y después de migrar.
- Cambiar la cadena de un proyecto no altera ningún payout guardado.
- Arrastrar funciona con ratón, con pulsación larga en Android real y sin arrastre mediante teclado.
- Sin scroll lateral en 1280, 900, 700, 375 y 320, también en la imagen Linux de CI.

## Lo que debe respetarse

- PROD solo lo pulsa Miguel. Master se publica en un espejo público: ningún host ni IP en el repositorio.
- El flujo `advisor` y la skill `pleno` antes de aterrizar la rama, como dice `software/AGENTS.md`.
- La validación de UI de ese mismo archivo, y su regla de textos: acciones o una conclusión, una línea corta cada una.
- Una fase por rama `phase-58`, aterrizada en un solo commit.
- Nunca reiniciar TELLOTRON. Tests e2e con 6 workers.

## Sin resolver

Nada.
