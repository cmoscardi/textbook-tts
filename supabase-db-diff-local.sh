#!/bin/bash
PGSSLMODE=disable supabase db diff -f add_file_select_policy
