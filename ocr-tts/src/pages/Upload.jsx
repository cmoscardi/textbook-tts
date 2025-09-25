import { useState } from 'react';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function Upload() {
  const { session } = useSession();
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    setSelectedFile(file);
    setUploadStatus('');
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadStatus('Please select a file first');
      return;
    }

    if (!session?.user) {
      setUploadStatus('User not authenticated');
      return;
    }

    setIsUploading(true);
    setUploadStatus('Uploading...');

    try {
      // Generate unique filename with timestamp
      const timestamp = Date.now();
      const fileExtension = selectedFile.name.split('.').pop();
      const fileName = `${timestamp}_${selectedFile.name}`;
      const filePath = `${session.user.id}/${fileName}`;

      // Upload file to Supabase storage
      const { data: uploadData, error: uploadError } = await supabase.storage
        .from('files')
        .upload(filePath, selectedFile);

      if (uploadError) {
        throw uploadError;
      }
      console.log("UPLOAD HAPPEN??");

      // Calculate checksum (simplified - you might want to use a proper SHA-256 implementation)
      const checksum = await calculateFileChecksum(selectedFile);

      // Create database record
      const { error: dbError } = await supabase
        .from('files')
        .insert({
          user_id: session.user.id,
          file_name: selectedFile.name,
          file_path: uploadData.path,
          file_size: selectedFile.size,
          mime_type: selectedFile.type,
          checksum: checksum
        });

      if (dbError) {
        // If database insert fails, try to clean up the uploaded file
        await supabase.storage.from('files').remove([filePath]);
        throw dbError;
      }

      setUploadStatus('File uploaded successfully!');
      setSelectedFile(null);
    } catch (error) {
      console.error('Upload error:', error);
      setUploadStatus(`Upload failed: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Simple checksum calculation function
  const calculateFileChecksum = async (file) => {
    const arrayBuffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  };

  return (
    <div className="max-w-md mx-auto bg-white rounded-lg shadow-md p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Upload File</h1>
      
      <div className="space-y-4">
        <div>
          <label htmlFor="file-upload" className="block text-sm font-medium text-gray-700 mb-2">
            Choose file to upload
          </label>
          <input
            id="file-upload"
            type="file"
            onChange={handleFileSelect}
            accept=".pdf"
            className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
        </div>

        {selectedFile && (
          <div className="text-sm text-gray-600">
            Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!selectedFile || isUploading}
          className="w-full py-2 px-4 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          {isUploading ? 'Uploading...' : 'Upload File'}
        </button>

        {uploadStatus && (
          <div className={`text-sm p-2 rounded ${
            uploadStatus.includes('success') 
              ? 'text-green-700 bg-green-100' 
              : uploadStatus.includes('failed') 
              ? 'text-red-700 bg-red-100'
              : 'text-blue-700 bg-blue-100'
          }`}>
            {uploadStatus}
          </div>
        )}
      </div>
    </div>
  );
}
