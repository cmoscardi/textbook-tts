import { useState, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function Player() {
  const { fileId } = useParams();
  const { session } = useSession();
  const [file, setFile] = useState(null);
  const [conversion, setConversion] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const audioRef = useRef(null);

  useEffect(() => {
    if (session?.user && fileId) {
      fetchFileAndConversion();
    }
  }, [session, fileId]);

  const fetchFileAndConversion = async () => {
    try {
      setLoading(true);
      setError('');

      // Fetch file data
      const { data: fileData, error: fileError } = await supabase
        .from('files')
        .select('*')
        .eq('file_id', fileId)
        .eq('user_id', session.user.id)
        .single();

      if (fileError) {
        if (fileError.code === 'PGRST116') {
          setError('File not found or you do not have access to this file');
        } else {
          throw fileError;
        }
        return;
      }

      setFile(fileData);

      // Fetch conversion data
      const { data: conversionData, error: conversionError } = await supabase
        .from('file_conversions')
        .select('*')
        .eq('file_id', fileId)
        .order('created_at', { ascending: false })
        .limit(1)
        .single();

      if (conversionError) {
        setError('No audio conversion found for this file');
        return;
      }

      if (conversionData.status !== 'completed') {
        setError(`Audio conversion is ${conversionData.status}. Please wait for conversion to complete.`);
        return;
      }

      if (!conversionData.file_path) {
        setError('Audio file path not found');
        return;
      }

      setConversion(conversionData);

      // Generate signed URL for audio file
      const { data: urlData, error: urlError } = await supabase.storage
        .from('files')
        .createSignedUrl(conversionData.file_path, 3600); // 1 hour expiry

      if (urlError) {
        console.error('Error generating signed URL:', urlError);
        setError('Failed to load audio file');
        return;
      }

      if (!urlData?.signedUrl) {
        setError('Failed to generate audio URL');
        return;
      }

      setAudioUrl(urlData.signedUrl);

    } catch (err) {
      console.error('Error fetching file:', err);
      setError('Failed to load audio file');
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

  const handleDownload = async () => {
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
        <div className="text-gray-600">Loading audio player...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <Link
            to="/files"
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
    <div className="max-w-4xl mx-auto">
      {/* Header with back button */}
      <div className="mb-6">
        <Link
          to="/files"
          className="inline-flex items-center text-blue-600 hover:text-blue-800 mb-4"
        >
          <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to Files
        </Link>

        {/* File metadata */}
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

            {/* Download button */}
            <button
              onClick={handleDownload}
              className="ml-4 px-3 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors flex items-center gap-2"
              title="Download audio file"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Download
            </button>
          </div>
        </div>
      </div>

      {/* Audio Player */}
      <div className="bg-white shadow rounded-lg p-8">
        <div className="flex flex-col items-center">
          <div className="w-full max-w-2xl">
            <div className="mb-6 text-center">
              <div className="inline-flex items-center justify-center w-20 h-20 bg-green-100 rounded-full mb-4">
                <svg className="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-800 mb-2">Audio Player</h2>
              <p className="text-gray-600 text-sm">Listen to your converted audiobook</p>
            </div>

            {audioUrl && (
              <audio
                ref={audioRef}
                controls
                className="w-full"
                preload="metadata"
              >
                <source src={audioUrl} type="audio/mpeg" />
                Your browser does not support the audio element.
              </audio>
            )}

            <div className="mt-4 text-center text-sm text-gray-500">
              <p>File: {file.file_name.replace('.pdf', '.mp3')}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
