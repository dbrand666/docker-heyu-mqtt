#!/bin/sh
set -e

log(){
  echo "$(date -Iseconds): $@" 1>&2
}

HEYUCONFIG="/etc/heyu/x10.conf"

log "Configuring Heyu..."

# Generate basic X10 configuration file, only need TTY port

echo -e "TTY\t\t  ${DEVICE}\n" > "${HEYUCONFIG}"

# Export enviornment variables for the main script

# Export environement if CM17 is defined

if $USE_CM17 ;then
  log "CM17 is enabled"
  export CM17="True"
else
  log "CM11 is enabled"
fi
  
# Start heyu engine, or restart after container restart
heyu engine || heyu restart

# Run main script
python -u x10mqtt.py
