import { useState, useEffect, useRef } from 'react';
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
  const audioRef = useRef(null);
  const pollingIntervalRef = useRef(null);
  const currentJobIdRef = useRef(null);
  const isMountedRef = useRef(true);

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
    };
  }, []);

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
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [conversion]);

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
        setError('This file has not been parsed yet. Please return to the files page and wait for parsing to complete.');
        return;
      }

      setFile(data);

      // Fetch conversion data (optional - for audio player)
      const { data: conversionData, error: conversionError } = await supabase
        .from('file_conversions')
        .select('*')
        .eq('file_id', fileId)
        .order('created_at', { ascending: false })
        .limit(1)
        .single();

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
    const blob = new Blob([file.parsed_text], { type: 'text/markdown' });
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
            </div>
          </div>
        </div>
      </div>

      {/* Audio Conversion Section */}
      <div className="mb-6 bg-white shadow rounded-lg p-6">
        {/* Show audio player if conversion is completed */}
        {audioUrl && conversion?.status === 'completed' ? (
          <>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-12 h-12 bg-green-100 rounded-full">
                  <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                    </svg>
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-gray-800">Audio Player</h2>
                    <p className="text-sm text-gray-600">Listen to your converted audiobook</p>
                  </div>
                </div>
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
                </div>
              <audio
                ref={audioRef}
                controls
                className="w-full"
                preload="metadata"
              >
                <source src={audioUrl} type="audio/mpeg" />
                Your browser does not support the audio element.
              </audio>
            </>
          ) : conversion && (conversion.status === 'pending' || conversion.status === 'running') ? (
            /* Show conversion progress */
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 bg-blue-100 rounded-full">
                <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
          ) : (
            /* Show convert button if no conversion exists */
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 bg-gray-100 rounded-full">
                <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                </svg>
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-gray-800 mb-1">Convert to Audio</h2>
                <p className="text-sm text-gray-600 mb-3">Generate an audio version of this document</p>
                <button
                  onClick={handleConvert}
                  className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  Convert to MP3
                </button>
              </div>
            </div>
          )}
        </div>

      {/* Markdown content */}
      <div className="bg-white shadow rounded-lg p-8">
        <article className="prose prose-lg max-w-none text-gray-900 prose-headings:text-gray-900 prose-p:text-gray-800 prose-li:text-gray-800 prose-strong:text-gray-900 prose-a:text-blue-600 prose-code:text-pink-700 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-table:text-gray-800">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {file.parsed_text}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
