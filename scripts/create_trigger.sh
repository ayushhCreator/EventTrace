#!/bin/bash
gcloud builds triggers create github \
  --trigger-config=scripts/trigger_config.yaml \
  --project=supersahayak
