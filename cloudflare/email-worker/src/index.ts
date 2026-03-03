import PostalMime from 'postal-mime';

interface Env {
  MLSERVICE_HOST: string;
  MLSERVICE_AUTH_KEY: string;
}

export default {
  async email(message: ForwardableEmailMessage, env: Env, ctx: ExecutionContext) {
    const parser = new PostalMime();
    const rawEmail = new Response(message.raw);
    const arrayBuffer = await rawEmail.arrayBuffer();
    const parsed = await parser.parse(arrayBuffer);

    // Find first PDF attachment, if any
    const pdfAttachment = parsed.attachments?.find(
      (a) => a.mimeType === 'application/pdf'
    );

    // Convert attachment to base64 if present
    let attachment_base64: string | null = null;
    if (pdfAttachment) {
      const bytes = new Uint8Array(pdfAttachment.content);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      attachment_base64 = btoa(binary);
    }

    const payload = {
      sender: message.from,
      subject: parsed.subject || '(no subject)',
      has_attachment: !!pdfAttachment,
      attachment_base64,
      attachment_filename: pdfAttachment?.filename || null,
      text_body: parsed.text || null,
      html_body: parsed.html || null,
    };

    const response = await fetch(`${env.MLSERVICE_HOST}/ingest-email`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ML-Auth-Key': env.MLSERVICE_AUTH_KEY,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      message.setReject(`ML service error: ${response.status}`);
    }
  },
};
