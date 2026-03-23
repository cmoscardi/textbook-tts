import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { verifyJwt } from '../_shared/auth.ts'

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

    // Verify the user is authenticated (local JWT verification — no GoTrue network call)
    const user = await verifyJwt(authHeader.replace('Bearer ', ''))

    if (!user) {
      return new Response(
        JSON.stringify({ error: 'Invalid or expired token' }),
        {
          status: 401,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    // GET — poll for synthesis result
    if (req.method === 'GET') {
      const url = new URL(req.url)
      const taskId = url.searchParams.get('task_id')
      const sentenceId = url.searchParams.get('sentence_id')

      if (!taskId) {
        return new Response(
          JSON.stringify({ error: 'Missing task_id query parameter' }),
          {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          }
        )
      }

      const mlResponse = await fetch(`${mlServiceHost}/synthesize/${taskId}`, {
        method: 'GET',
        headers: {
          'ML-Auth-Key': mlServiceAuthKey,
        },
      })

      if (!mlResponse.ok) {
        const errorText = await mlResponse.text()
        console.error('ML service error:', errorText)
        return new Response(
          JSON.stringify({ error: 'Failed to get synthesis status' }),
          {
            status: mlResponse.status,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          }
        )
      }

      const contentType = mlResponse.headers.get('Content-Type') || ''

      if (contentType.includes('audio/')) {
        const audioBytes = await mlResponse.arrayBuffer()
        const audioDuration = mlResponse.headers.get('X-Audio-Duration') || '0'

        // Cache to Supabase storage
        if (sentenceId) {
          const storagePath = `${user.id}/sentences/${sentenceId}.mp3`
          const { error: uploadError } = await supabase.storage
            .from('files')
            .upload(storagePath, audioBytes, {
              contentType: 'audio/mpeg',
              upsert: true,
            })

          if (!uploadError) {
            await supabase
              .from('page_sentences')
              .update({ audio_path: storagePath })
              .eq('sentence_id', sentenceId)
          } else {
            console.error('Failed to cache audio:', uploadError)
          }
        }

        return new Response(audioBytes, {
          headers: {
            ...corsHeaders,
            'Content-Type': 'audio/mpeg',
            'X-Audio-Duration': audioDuration,
          }
        })
      } else {
        // Still processing — proxy JSON status
        const body = await mlResponse.text()
        return new Response(body, {
          headers: {
            ...corsHeaders,
            'Content-Type': 'application/json',
          }
        })
      }
    }

    // POST — submit synthesis request (or serve from cache)
    const { text, file_id, sentence_id } = await req.json()

    if (!text || !file_id) {
      return new Response(
        JSON.stringify({ error: 'Missing text or file_id' }),
        {
          status: 400,
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

    // Check cache: if sentence already has audio in storage, serve it directly
    if (sentence_id) {
      const { data: sentenceData } = await supabase
        .from('page_sentences')
        .select('audio_path')
        .eq('sentence_id', sentence_id)
        .single()

      if (sentenceData?.audio_path) {
        const { data: audioData, error: downloadError } = await supabase.storage
          .from('files')
          .download(sentenceData.audio_path)

        if (!downloadError && audioData) {
          const arrayBuffer = await audioData.arrayBuffer()
          return new Response(arrayBuffer, {
            headers: {
              ...corsHeaders,
              'Content-Type': 'audio/mpeg',
            }
          })
        }
        // If download failed, fall through to re-synthesize
        console.error('Cache download failed, re-synthesizing:', downloadError)
      }
    }

    // Cache miss — submit synthesis task to ML service
    const mlResponse = await fetch(`${mlServiceHost}/synthesize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ML-Auth-Key': mlServiceAuthKey,
      },
      body: JSON.stringify({ text })
    })

    if (!mlResponse.ok) {
      const errorText = await mlResponse.text()
      console.error('ML service error:', errorText)
      return new Response(
        JSON.stringify({ error: 'Failed to submit synthesis task' }),
        {
          status: mlResponse.status,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        }
      )
    }

    const result = await mlResponse.json()
    return new Response(
      JSON.stringify(result),
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
