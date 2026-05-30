#!/bin/bash

IFS=$'\n'


fail=0
ok=0

for task in `cat tasks.txt | grep -vE "^\#"`; do 
	synergia create-task --name test --github-url "$task" 
	
	if [ $? -ne 0 ]; then
		fail=`bc <<< "$fail + 1"`
	else
		ok=`bc <<< "$ok + 1"`
	fi
done


echo -n "Se han procesado correctamente: "
echo "$ok"
echo -n "Se han procesado incorrectamente: "
echo "$fail"
