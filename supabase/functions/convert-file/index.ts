import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    )

    const { file_id } = await req.json()

    if (!file_id) {
      return new Response(
        JSON.stringify({ error: 'Missing file_id' }),
        {
          status: 400,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Get the JWT token from the Authorization header
    const authHeader = req.headers.get('Authorization')
    if (!authHeader) {
      return new Response(
        JSON.stringify({ error: 'Missing authorization header' }),
        {
          status: 401,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Verify the user is authenticated and get their user_id
    const { data: { user }, error: userError } = await supabase.auth.getUser(
      authHeader.replace('Bearer ', '')
    )

    if (userError || !user) {
      return new Response(
        JSON.stringify({ error: 'Invalid or expired token' }),
        {
          status: 401,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Verify the user owns the file
    const { data: fileData, error: fileError } = await supabase
      .from('files')
      .select('user_id')
      .eq('file_id', file_id)
      .single()

    if (fileError || !fileData) {
      console.error('File lookup error:', fileError)
      return new Response(
        JSON.stringify({ error: 'File not found' }),
        {
          status: 404,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    if (fileData.user_id !== user.id) {
      console.error(`Unauthorized: User ${user.id} attempted to access file owned by ${fileData.user_id}`)
      return new Response(
        JSON.stringify({ error: 'Unauthorized: You do not own this file' }),
        {
          status: 403,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Check usage quota
    console.log(`Checking conversion quota for user ${user.id}`)
    const { data: canConvert, error: quotaError } = await supabase
      .rpc('can_user_convert', { p_user_id: user.id })

    if (quotaError) {
      console.error('Quota check error:', quotaError)
      return new Response(
        JSON.stringify({ error: 'Failed to check usage quota' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    if (!canConvert) {
      // Get current usage for details
      const { data: usage, error: usageError } = await supabase
        .rpc('get_current_usage', { p_user_id: user.id })

      console.log(`Conversion limit reached for user ${user.id}. Usage:`, usage)

      return new Response(
        JSON.stringify({
          error: 'Conversion limit reached',
          message: `You've reached your ${usage?.period_type || 'monthly'} conversion limit`,
          usage: {
            used: usage?.conversions_used || 0,
            limit: usage?.conversion_limit || 0,
            period_type: usage?.period_type,
            period_end: usage?.period_end
          }
        }),
        {
          status: 429,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Increment usage counter (do this BEFORE calling ML service to prevent race conditions)
    console.log(`Incrementing usage counter for user ${user.id}`)
    const { error: incrementError } = await supabase
      .rpc('increment_usage', { p_user_id: user.id })

    if (incrementError) {
      console.error('Error incrementing usage:', incrementError)
      return new Response(
        JSON.stringify({ error: 'Failed to update usage tracking' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // Call the ML service with just the file_id
    // The ML service will handle fetching file metadata and generating signed URLs
    const mlServiceHost = Deno.env.get('MLSERVICE_HOST') ?? 'http://localhost:5000'
    const mlServiceAuthKey = Deno.env.get('MLSERVICE_AUTH_KEY')

    if (!mlServiceAuthKey) {
      console.error('MLSERVICE_AUTH_KEY not configured')
      return new Response(
        JSON.stringify({ error: 'ML service configuration error' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    console.log("ML Service Host:", mlServiceHost);

    const mlResponse = await fetch(`${mlServiceHost}/convert`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ML-Auth-Key': mlServiceAuthKey,
      },
      body: JSON.stringify({
        file_id: file_id
      })
    })

    if (!mlResponse.ok) {
      const errorText = await mlResponse.text()
      console.error('ML service error:', errorText)
      return new Response(
        JSON.stringify({ error: 'Failed to start audio conversion' }),
        {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    const mlData = await mlResponse.json()

    return new Response(
      JSON.stringify(mlData),
      {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      }
    )

  } catch (error) {
    console.error('Edge function error:', error)
    return new Response(
      JSON.stringify({ error: 'Internal server error' }),
      {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      }
    )
  }
})
