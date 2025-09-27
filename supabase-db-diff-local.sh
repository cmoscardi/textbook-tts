#!/bin/bash
PGSSLMODE=disable npx supabase db diff -f $1
