import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function FileViewer() {
  const { fileId } = useParams();
  const { session } = useSession();
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [conversion, setConversion] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const pollingIntervalRef = useRef(null);
  const currentJobIdRef = useRef(null);
  const isMountedRef = useRef(true);

  // Progressive parsing state
  const [isParsingInProgress, setIsParsingInProgress] = useState(false);
  const [parsingProgress, setParsingProgress] = useState(0);
  const [pageMarkdowns, setPageMarkdowns] = useState([]);
  const parsingPollingRef = useRef(null);

  // Sentence-by-sentence playback state
  const [sentences, setSentences] = useState([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentSentenceIdx, setCurrentSentenceIdx] = useState(0);
  const [isSynthesizing, setIsSynthesizing] = useState(false);
  const sentenceAudioCache = useRef(new Map());
  const currentAudioRef = useRef(null);
  const stopRequestedRef = useRef(false);

  useEffect(() => {
    if (session?.user && fileId) {
      fetchFile();
    }
  }, [session, fileId]);

  // Set mounted state and cleanup polling on unmount
  useEffect(() => {
    isMountedRef.current = true;
    console.log('[Mount] FileViewer mounted');

    return () => {
      console.log('[Mount] FileViewer unmounting');
      isMountedRef.current = false;
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        currentJobIdRef.current = null;
      }
      if (parsingPollingRef.current) {
        clearInterval(parsingPollingRef.current);
        parsingPollingRef.current = null;
      }
      // Clean up playback
      stopRequestedRef.current = true;
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
        currentAudioRef.current = null;
      }
      for (const blobUrl of sentenceAudioCache.current.values()) {
        URL.revokeObjectURL(blobUrl);
      }
      sentenceAudioCache.current.clear();
    };
  }, []);

  // Persist playback position to database (debounced)
  useEffect(() => {
    if (sentences.length === 0) return;
    const timeout = setTimeout(() => {
      supabase
        .from('files')
        .update({ playback_position: currentSentenceIdx })
        .eq('file_id', fileId)
        .eq('user_id', session.user.id)
        .then(({ error }) => {
          if (error) console.error('Failed to save playback position:', error);
        });
    }, 500);
    return () => clearTimeout(timeout);
  }, [currentSentenceIdx, fileId, sentences.length, session?.user?.id]);

  // Start polling when conversion changes to pending/running
  useEffect(() => {
    if (conversion && (conversion.status === 'pending' || conversion.status === 'running')) {
      startPolling(conversion.job_id);
    }
  }, [conversion]);

  // Page Visibility API - force check when tab becomes visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (conversion && conversion.job_id &&
            (conversion.status === 'pending' || conversion.status === 'running')) {
          console.log('Page visible - forcing conversion status check');
          checkConversionStatus(conversion.job_id);
        }
        if (isParsingInProgress) {
          console.log('Page visible - forcing parsing status check');
          pollParsingStatus();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [conversion, isParsingInProgress]);

  // --- Conversion polling (existing) ---

  const checkConversionStatus = async (jobId) => {
    console.log('[Poll] Checking status for job:', jobId);

    if (!isMountedRef.current) {
      console.log('[Poll] Component unmounted, skipping');
      return;
    }

    try {
      const { data, error } = await supabase
        .from('file_conversions')
        .select('*')
        .eq('job_id', jobId)
        .limit(1)
        .maybeSingle();

      if (error) {
        console.error('[Poll] Error checking conversion status:', error);
        return;
      }

      if (data) {
        console.log('[Poll] Conversion status update:', data.status, data.job_completion + '%');
        setConversion(data);

        // Stop polling if completed or failed
        if (data.status === 'completed' || data.status === 'failed') {
          console.log('[Poll] Conversion finished, stopping polling');
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
            currentJobIdRef.current = null;
          }

          // Generate audio URL if completed
          if (data.status === 'completed' && data.file_path) {
            const { data: urlData, error: urlError } = await supabase.storage
              .from('files')
              .createSignedUrl(data.file_path, 3600);

            if (!urlError && urlData?.signedUrl) {
              setAudioUrl(urlData.signedUrl);
            }
          }
        }
      } else {
        console.log('[Poll] No conversion record found yet for job:', jobId);
      }
    } catch (err) {
      console.error('[Poll] Exception polling conversion status:', err);
    }
  };

  const startPolling = (jobId) => {
    if (!jobId || jobId === 'pending') {
      console.warn('Invalid job_id for polling:', jobId);
      return;
    }

    if (currentJobIdRef.current === jobId) {
      console.log('Already polling for job:', jobId);
      return;
    }

    if (pollingIntervalRef.current) {
      console.log('Clearing existing polling interval for different job');
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }

    console.log('Starting polling for job:', jobId);
    currentJobIdRef.current = jobId;

    checkConversionStatus(jobId);

    const intervalId = setInterval(() => {
      console.log('[Interval] Firing for job:', jobId);
      checkConversionStatus(jobId);
    }, 3000);
    pollingIntervalRef.current = intervalId;
    console.log('Polling interval created:', intervalId);
  };

  const handleConvert = async () => {
    const { data: { session: currentSession } } = await supabase.auth.getSession();
    if (!currentSession) return;

    const { data, error } = await supabase.functions.invoke('convert-file', {
      body: { file_id: fileId },
      headers: { Authorization: `Bearer ${currentSession.access_token}` }
    });
    if (error) { console.error('Conversion failed:', error); return; }

    setConversion({ job_id: data.id, status: 'pending', job_completion: 0 });
  };

  // --- Parsing polling (progressive loading) ---

  const fetchPageMarkdowns = async () => {
    const { data, error } = await supabase
      .from('file_pages')
      .select('markdown_text')
      .eq('file_id', fileId)
      .order('page_number', { ascending: true });

    if (error) {
      console.error('[Parsing] Error fetching page markdowns:', error);
      return [];
    }

    const texts = (data || [])
      .map(row => row.markdown_text)
      .filter(Boolean);
    return texts;
  };

  const pollParsingStatus = async () => {
    if (!isMountedRef.current) return;

    try {
      // Check parsing status
      const { data: parsingData, error: parsingError } = await supabase
        .from('file_parsings')
        .select('status, job_completion')
        .eq('file_id', fileId)
        .order('created_at', { ascending: false })
        .limit(1)
        .maybeSingle();

      if (parsingError) {
        console.error('[Parsing] Error checking parsing status:', parsingError);
        return;
      }

      if (!parsingData) return;

      setParsingProgress(parsingData.job_completion || 0);

      // Fetch updated page markdowns
      const texts = await fetchPageMarkdowns();
      setPageMarkdowns(texts);

      // Fetch sentences progressively so Play button appears during parsing
      const { data: sentenceData } = await supabase
        .from('page_sentences')
        .select('sentence_id, text, sequence_number')
        .eq('file_id', fileId)
        .order('sequence_number', { ascending: true });

      if (sentenceData && sentenceData.length > 0) {
        setSentences(sentenceData);
        setCurrentSentenceIdx(prev => Math.min(prev, sentenceData.length - 1));
      }

      if (parsingData.status === 'completed') {
        console.log('[Parsing] Parsing completed, re-fetching file');
        // Stop parsing polling
        if (parsingPollingRef.current) {
          clearInterval(parsingPollingRef.current);
          parsingPollingRef.current = null;
        }
        setIsParsingInProgress(false);

        // Re-fetch file to get raw_markdown
        const { data: freshFile, error: fileError } = await supabase
          .from('files')
          .select('*')
          .eq('file_id', fileId)
          .eq('user_id', session.user.id)
          .single();

        if (!fileError && freshFile) {
          setFile(freshFile);
        }

        // Fetch conversion data now that parsing is done
        const { data: conversionData, error: conversionError } = await supabase
          .from('file_conversions')
          .select('*')
          .eq('file_id', fileId)
          .order('created_at', { ascending: false })
          .limit(1)
          .maybeSingle();

        if (!conversionError && conversionData) {
          setConversion(conversionData);
          if (conversionData.status === 'completed' && conversionData.file_path) {
            const { data: urlData, error: urlError } = await supabase.storage
              .from('files')
              .createSignedUrl(conversionData.file_path, 3600);
            if (!urlError && urlData?.signedUrl) {
              setAudioUrl(urlData.signedUrl);
            }
          }
        }
      } else if (parsingData.status === 'failed') {
        if (parsingPollingRef.current) {
          clearInterval(parsingPollingRef.current);
          parsingPollingRef.current = null;
        }
        setIsParsingInProgress(false);
        setError('Parsing failed. Please try uploading the file again.');
      }
    } catch (err) {
      console.error('[Parsing] Exception polling parsing status:', err);
    }
  };

  const startParsingPolling = () => {
    if (parsingPollingRef.current) {
      clearInterval(parsingPollingRef.current);
    }

    // Poll immediately
    pollParsingStatus();

    // Then poll every 3 seconds
    parsingPollingRef.current = setInterval(() => {
      pollParsingStatus();
    }, 3000);
  };

  // --- Sentence-by-sentence playback ---

  const synthesizeSentence = useCallback(async (idx) => {
    if (sentenceAudioCache.current.has(idx)) {
      return sentenceAudioCache.current.get(idx);
    }

    const { data: { session: currentSession } } = await supabase.auth.getSession();
    if (!currentSession) throw new Error('Not authenticated');

    const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
    const response = await fetch(`${supabaseUrl}/functions/v1/play-sentence`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${currentSession.access_token}`,
        'apikey': import.meta.env.VITE_SUPABASE_ANON_KEY,
      },
      body: JSON.stringify({ text: sentences[idx].text, file_id: fileId }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Synthesis failed: ${errorText}`);
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    sentenceAudioCache.current.set(idx, blobUrl);
    return blobUrl;
  }, [sentences, fileId]);

  const playFromIndex = useCallback(async (startIdx) => {
    stopRequestedRef.current = false;
    setIsPlaying(true);

    for (let i = startIdx; i < sentences.length; i++) {
      if (stopRequestedRef.current) break;

      setCurrentSentenceIdx(i);
      setIsSynthesizing(true);

      let blobUrl;
      try {
        blobUrl = await synthesizeSentence(i);
      } catch (err) {
        console.error('Synthesis error:', err);
        break;
      }

      if (stopRequestedRef.current) break;
      setIsSynthesizing(false);

      // Pre-fetch next sentence
      if (i + 1 < sentences.length) {
        synthesizeSentence(i + 1).catch(() => {});
      }

      // Play current sentence
      const audio = new Audio(blobUrl);
      currentAudioRef.current = audio;

      await new Promise((resolve) => {
        audio.addEventListener('ended', resolve);
        audio.addEventListener('error', resolve);
        audio.play().catch(resolve);
      });

      currentAudioRef.current = null;
      if (stopRequestedRef.current) break;
    }

    setIsPlaying(false);
    setIsSynthesizing(false);
  }, [sentences, synthesizeSentence]);

  const handlePlayPause = useCallback(() => {
    if (isPlaying) {
      stopRequestedRef.current = true;
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
        currentAudioRef.current = null;
      }
      setIsPlaying(false);
      setIsSynthesizing(false);
    } else {
      playFromIndex(currentSentenceIdx);
    }
  }, [isPlaying, currentSentenceIdx, playFromIndex]);

  const handleProgressClick = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fraction = (e.clientX - rect.left) / rect.width;
    const idx = Math.min(Math.floor(fraction * sentences.length), sentences.length - 1);
    setCurrentSentenceIdx(idx);
    if (isPlaying) {
      stopRequestedRef.current = true;
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
        currentAudioRef.current = null;
      }
      setTimeout(() => playFromIndex(idx), 50);
    }
  }, [sentences, isPlaying, playFromIndex]);

  // --- File fetching ---

  const fetchFile = async () => {
    try {
      setLoading(true);
      setError('');

      const { data, error: fetchError } = await supabase
        .from('files')
        .select('*')
        .eq('file_id', fileId)
        .eq('user_id', session.user.id)
        .single();

      if (fetchError) {
        if (fetchError.code === 'PGRST116') {
          setError('File not found or you do not have access to this file');
        } else {
          throw fetchError;
        }
        return;
      }

      if (!data.parsed_text) {
        // File not fully parsed yet — check if parsing is in progress
        const { data: parsingData, error: parsingError } = await supabase
          .from('file_parsings')
          .select('status, job_completion')
          .eq('file_id', fileId)
          .order('created_at', { ascending: false })
          .limit(1)
          .maybeSingle();

        if (parsingError) {
          console.error('[Parsing] Error checking parsing status:', parsingError);
        }

        if (parsingData && (parsingData.status === 'running' || parsingData.status === 'pending')) {
          // Parsing is in progress — set up progressive display
          setFile(data);
          setIsParsingInProgress(true);
          setParsingProgress(parsingData.job_completion || 0);

          // Fetch any already-parsed page markdowns
          const texts = await fetchPageMarkdowns();
          setPageMarkdowns(texts);

          // Start polling for more pages
          startParsingPolling();
        } else if (parsingData && parsingData.status === 'failed') {
          setError('Parsing failed. Please try uploading the file again.');
          return;
        } else {
          setError('This file has not been parsed yet. Please return to the files page and upload it again.');
          return;
        }
      } else {
        setFile(data);

        // Fetch sentences for playback
        const { data: sentenceData } = await supabase
          .from('page_sentences')
          .select('sentence_id, text, sequence_number')
          .eq('file_id', fileId)
          .order('sequence_number', { ascending: true });

        if (sentenceData && sentenceData.length > 0) {
          setSentences(sentenceData);
          setCurrentSentenceIdx(Math.min(data.playback_position || 0, sentenceData.length - 1));
        }
      }

      // Fetch conversion data (optional - for audio player)
      const { data: conversionData, error: conversionError } = await supabase
        .from('file_conversions')
        .select('*')
        .eq('file_id', fileId)
        .order('created_at', { ascending: false })
        .limit(1)
        .maybeSingle();

      // Set conversion data if it exists (regardless of status)
      if (!conversionError && conversionData) {
        setConversion(conversionData);

        // Only generate audio URL if conversion is completed and has file_path
        if (conversionData.status === 'completed' && conversionData.file_path) {
          // Generate signed URL for audio file
          const { data: urlData, error: urlError } = await supabase.storage
            .from('files')
            .createSignedUrl(conversionData.file_path, 3600); // 1 hour expiry

          if (!urlError && urlData?.signedUrl) {
            setAudioUrl(urlData.signedUrl);
          }
        }
      }

    } catch (err) {
      console.error('Error fetching file:', err);
      setError('Failed to load file');
    } finally {
      setLoading(false);
    }
  };

  // --- Display text logic ---

  // Use raw_markdown if available (completed parsing), otherwise join per-page markdowns
  const displayMarkdown = file?.raw_markdown
    || (pageMarkdowns.length > 0 ? pageMarkdowns.join('\n\n') : null);

  // --- Helpers ---

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const handleDownloadMarkdown = () => {
    const text = file?.raw_markdown || file?.parsed_text || displayMarkdown || '';
    const blob = new Blob([text], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${file.file_name.replace('.pdf', '')}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleDownloadAudio = async () => {
    if (!conversion?.file_path) return;

    try {
      const { data, error } = await supabase.storage
        .from('files')
        .download(conversion.file_path);

      if (error) throw error;

      const url = URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${file.file_name.replace('.pdf', '')}.mp3`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download error:', err);
      alert('Failed to download audio file');
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-600">Loading file...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <Link
            to="/app/files"
            className="inline-flex items-center text-blue-600 hover:text-blue-800"
          >
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Back to Files
          </Link>
        </div>
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      </div>
    );
  }

  if (!file) return null;

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header with back button and file info */}
      <div className="mb-6">
        <Link
          to="/app/files"
          className="inline-flex items-center text-blue-600 hover:text-blue-800 mb-4"
        >
          <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to Files
        </Link>

        <div className="bg-white shadow rounded-lg p-6">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <h1 className="text-2xl font-bold text-gray-800 mb-2">{file.file_name}</h1>
              <div className="flex flex-wrap gap-4 text-sm text-gray-600">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <span>Uploaded: {formatDate(file.uploaded_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                  </svg>
                  <span>Size: {formatFileSize(file.file_size)}</span>
                </div>
                {file.parsed_at && (
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>Parsed: {formatDate(file.parsed_at)}</span>
                  </div>
                )}
                {conversion && (
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                    </svg>
                    <span>Converted: {formatDate(conversion.created_at)}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 ml-4">
              {displayMarkdown && (
                <button
                  onClick={handleDownloadMarkdown}
                  className="px-3 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors flex items-center gap-2"
                  title="Download as markdown file"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Download PDF
                </button>
              )}
              {/* Convert / conversion status / download MP3 */}
              {audioUrl && conversion?.status === 'completed' ? (
                <button
                  onClick={handleDownloadAudio}
                  className="px-3 py-2 text-sm bg-green-500 text-white rounded hover:bg-green-600 transition-colors flex items-center gap-2"
                  title="Download audio file"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Download MP3
                </button>
              ) : conversion && (conversion.status === 'pending' || conversion.status === 'running') ? (
                <div className="px-3 py-2 text-sm bg-blue-100 text-blue-700 rounded flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Converting {conversion.job_completion || 0}%
                </div>
              ) : isParsingInProgress ? (
                <div className="px-3 py-2 text-sm bg-yellow-100 text-yellow-700 rounded flex items-center gap-2" title="Available after parsing completes">
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Parsing {parsingProgress}%
                </div>
              ) : !isParsingInProgress && file?.parsed_text ? (
                <button
                  onClick={handleConvert}
                  className="px-3 py-2 text-sm bg-green-500 text-white rounded hover:bg-green-600 transition-colors flex items-center gap-2"
                  title="Convert to audio"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  Convert to MP3
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Sentence Player */}
      {sentences.length > 0 && (
        <div className="mb-6 bg-white shadow rounded-lg p-6">
          <div className="flex flex-col items-center">
            {/* Large play/pause button */}
            <button
              onClick={handlePlayPause}
              className="w-14 h-14 rounded-full bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
              title={isPlaying ? 'Pause' : 'Play'}
            >
              {isSynthesizing && !currentAudioRef.current ? (
                <svg className="animate-spin h-7 w-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              ) : isPlaying ? (
                <svg className="w-7 h-7" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="4" width="4" height="16" />
                  <rect x="14" y="4" width="4" height="16" />
                </svg>
              ) : (
                <svg className="w-9 h-9 ml-1" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M4 2v20l18-10z" />
                </svg>
              )}
            </button>

            {/* Progress bar */}
            <div
              className="w-full mt-4 bg-gray-200 rounded-full h-2 cursor-pointer"
              onClick={handleProgressClick}
              title="Click to jump to a sentence"
            >
              <div
                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                style={{ width: `${sentences.length > 0 ? ((currentSentenceIdx + 1) / sentences.length) * 100 : 0}%` }}
              ></div>
            </div>

            {/* Sentence counter */}
            <p className="mt-2 text-sm text-gray-600">
              Sentence {currentSentenceIdx + 1} of {sentences.length}
              {isSynthesizing && ' — synthesizing...'}
            </p>
          </div>
        </div>
      )}

      {/* Conversion progress */}
      {conversion && (conversion.status === 'pending' || conversion.status === 'running') && (
        <div className="mb-6 bg-white shadow rounded-lg p-6">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-10 h-10 bg-blue-100 rounded-full">
              <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold text-gray-800 mb-2">Converting to Audio</h2>
              <div className="flex items-center gap-3">
                <div className="flex-1 bg-gray-200 rounded-full h-3">
                  <div
                    className="bg-blue-600 h-3 rounded-full transition-all duration-500"
                    style={{ width: `${conversion?.job_completion || 0}%` }}
                  ></div>
                </div>
                <span className="text-sm font-medium text-gray-700 min-w-[3rem]">
                  {conversion?.job_completion || 0}%
                </span>
              </div>
              <p className="text-sm text-gray-600 mt-2">
                {conversion?.status === 'pending' ? 'Preparing to convert...' : 'Converting your document to audio...'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Markdown content */}
      <div className="bg-white shadow rounded-lg p-8">
        {isParsingInProgress && !displayMarkdown ? (
          /* Waiting for first page */
          <div className="flex flex-col items-center justify-center py-16 text-gray-500">
            <svg className="animate-spin h-8 w-8 text-blue-500 mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p className="text-lg font-medium">Waiting for first page...</p>
            <p className="text-sm mt-1">Parsing progress: {parsingProgress}%</p>
          </div>
        ) : displayMarkdown ? (
          <>
            <article className="prose prose-lg max-w-none text-gray-900 prose-headings:text-gray-900 prose-p:text-gray-800 prose-li:text-gray-800 prose-strong:text-gray-900 prose-a:text-blue-600 prose-code:text-pink-700 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-table:text-gray-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {displayMarkdown}
              </ReactMarkdown>
            </article>

            {/* Progress indicator at bottom during parsing */}
            {isParsingInProgress && (
              <div className="mt-8 pt-6 border-t border-gray-200">
                <div className="flex items-center gap-3 text-gray-500">
                  <svg className="animate-spin h-5 w-5 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span className="text-sm">Parsing more pages... {parsingProgress}% complete</span>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-gray-500 text-center py-8">No content available</div>
        )}
      </div>
    </div>
  );
}
