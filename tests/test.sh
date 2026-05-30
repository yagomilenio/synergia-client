#!/bin/bash


TASK_ID=1
PROCESS_ID=1
GITHUB_URL="https://github.com/yagomilenio/testRepositoryForParallel"


echo " TEST DE CONSENSO - SYNERGIA"

echo ""

# ---- 1. Crear usuarios ----
echo "[ 1/8 ] Creando usuarios..."
synergia sign-up-user --username rosendo --passwd 1234567890 --email rosendo@test.test
synergia sign-up-user --username louredo --passwd 1234567890 --email louredo@test.test
synergia sign-up-user --username xan     --passwd 1234567890 --email xan@test.test
synergia sign-up-user --username moncho  --passwd 1234567890 --email moncho@test.test
echo ""

# ---- 2. Rosendo crea tarea ----
echo "[ 2/8 ] Rosendo crea la tarea..."
synergia login-user --username rosendo --passwd 1234567890
synergia create-task --name test --github-url $GITHUB_URL
echo ""

# ---- 3. Louredo se suscribe (con error en repo) ----
echo "[ 3/8 ] Louredo se subscribe (resultado con error)..."
synergia login-user --username louredo --passwd 1234567890
synergia subscribe-task --task-id $TASK_ID
echo ""

# ---- 4. Pausa para modificar el repo ----

echo " PAUSA: Modifica el repositorio en GitHub para QUITAR el error"
echo " Cuando hayas hecho el commit, pulsa ENTER para continuar..."

read -p ""
echo ""

# ---- 5. Estado tras Louredo ----
echo "[ 4/8 ] Estado tras subscribe de Louredo:"
echo "--- Rosendo ---"
synergia get-user-details --username rosendo
echo ""
echo "--- Louredo ---"
synergia get-user-details --username louredo
echo ""

# ---- 6. Xan confirma proceso 1 ----
echo "[ 5/8 ] Xan confirma proceso 1 (resultado correcto, canonico no cambia)..."
synergia login-user --username xan --passwd 1234567890
synergia confirm-process --task-id $TASK_ID --process-id $PROCESS_ID
echo ""

echo "--- Estado tras confirmacion de Xan ---"
echo "--- Xan ---"
synergia get-user-details --username xan
echo ""

# ---- 7. Moncho confirma proceso 1 ----
echo "[ 6/8 ] Moncho confirma proceso 1 (canonico cambia)..."
synergia login-user --username moncho --passwd 1234567890
synergia confirm-process --task-id $TASK_ID --process-id $PROCESS_ID
echo ""

# ---- 8. Estado final ----
echo "[ 7/8 ] Estado final de todas las cuentas:"
echo ""
echo "--- Rosendo (publisher) ---"
synergia get-user-details --username rosendo
echo ""
echo "--- Louredo (resultado erroneo, pierde canonico) ---"
synergia get-user-details --username louredo
echo ""
echo "--- Xan (primer confirmador correcto) ---"
synergia get-user-details --username xan
echo ""
echo "--- Moncho (segundo confirmador, cambia canonico) ---"
synergia get-user-details --username moncho
echo ""






echo " TEST COMPLETADO"

