#!/bin/bash
echo "Checking for Russian characters in frontend/static/..."
grep -r -n "[а-яА-Я]" frontend/static/
if [ $? -eq 0 ]; then
    echo "FAIL: Russian characters found. See list above."
    exit 1
else
    echo "SUCCESS: No Russian characters found."
    exit 0
fi
