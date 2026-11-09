Vamos a construir la Fase 58 de Kronos: la cadena de 1 a 4 cuentas de un payout, confirmada con un botón y un sello, y las cuentas asignadas a cada proyecto arrastrándolas a unas cajitas. Las decisiones ya están tomadas con Miguel en una entrevista, y no hay nada abierto.

Lee primero, en este orden, dentro del repositorio de Kronos:
1. `.agents/changes/backlog/cadena-de-cuentas-payout/03-specification.md`
2. `.agents/changes/backlog/cadena-de-cuentas-payout/02-interview-responses.md`
3. `.agents/changes/backlog/cadena-de-cuentas-payout/01-request.md`

Dos decisiones van en contra de lo que se le recomendó (Q7 y Q11, elegir en la fila de un proyecto sin cuentas). Son firmes: respeta sus riesgos aceptados y no las reabras.

La especificación es una foto hecha de buena fe. Los documentos se quedan atrás, así que comprueba contra el código y contra INT lo que vaya a importar antes de construir encima, y corrige lo que encuentres desviado. En concreto, mira qué versión está de verdad en PROD, porque Miguel pudo pulsarlo después de escribirse esto: la migración tiene que funcionar desde ahí y desde v57.

El trabajo, como recomendación, va del menor riesgo a lo que depende de lo anterior:
1. Un mockup que se pueda probar de las cajitas, el arrastre, una fila de tres cuentas y el sello. Termina cuando Miguel lo valida; Miguel elige en mockups y su decisión manda sobre esta especificación.
2. Datos y migración. Termina cuando una copia con payouts de cada época migra sin mover ninguna cifra un céntimo.
3. La API de la cadena, confirmar, borrar, copia de seguridad y CSV.
4. Reordenar con el asa en cuentas, fuentes y plantillas, y que ese orden llegue a todos los selectores.
5. Las cajitas en Options, con ratón, pulsación larga y teclado.
6. La celda del payout en Weeks y en Days, con la cascada y sin autoguardado.
7. El sello y la limpieza de lo que quede sin uso.
Puedes reordenar o partir pasos si lo ves mejor. Lo firme es comprobar cada paso antes de construir el siguiente encima.

Límites duros:
- PROD solo lo pulsa Miguel, porque es su aplicación real con sus datos. Nunca lo despliegues desde una shell ni pulses su botón.
- Ningún host, IP ni nombre interno en el repositorio, porque master se publica en un espejo público.
- Nunca reinicies TELLOTRON sin su permiso en la conversación: es su PC diario y aloja GitLab.
- Ninguna cifra de un payout existente puede cambiar, porque es dinero real.

Orientación, de la que puedes apartarte si tienes un enfoque mejor, diciendo por qué:
- `software/AGENTS.md` y el `AGENTS.md` de Kronos ya describen el flujo, y `advisor` y `pleno` antes de aterrizar. No los repito.
- En esta fase los pasos de arrastre conviene probarlos pronto en el emulador Android, porque el arrastre táctil es lo que más fácil engaña en un navegador de escritorio.
- El runner de CI usa fuentes Linux: lo que se alinea por el ancho de un carácter pasa en Windows y falla allí. `bin/snapshots.py` ejecuta tests en esa imagen.
- Un check que no puede fallar no prueba nada, así que mira cada test nuevo ponerse rojo una vez.

Miguel quiere evidencia del estado real, no "parece que funciona": números concretos, capturas que hayas abierto y enlaces al pipeline. Cuando le pases algo para validar, dale pasos de clic en clic y empieza por la recarga forzada. Pregunta antes de cualquier cosa irreversible o que salga fuera, o que necesite sus secretos.

Para empezar: confirma el estado real (rama, versión en INT y en PROD, si queda algo sin archivar), comparte un plan breve y haz el mockup.

Subagentes, como recomendación: son buenos para construir cada unidad de código y para revisar en frío al final. Un subagente empieza sin contexto, así que su encargo debe valerse solo, con rutas, restricciones y criterio de éxito, y lo que informe es evidencia que hay que comprobar, no un resultado que repetir. No los uses para el mockup, que es una conversación con Miguel, ni para nada que toque PROD.
