// Populate Mono stores from the build base's trusted system CA bundle.
using System;
using System.IO;
using Mono.Security.X509;

class SyncMonoTrust
{
    static void Main()
    {
        string pem = File.ReadAllText("/etc/ssl/certs/ca-certificates.crt");
        int count = 0;
        foreach (string part in pem.Split(new[] {"-----BEGIN CERTIFICATE-----"}, StringSplitOptions.None))
        {
            int end = part.IndexOf("-----END CERTIFICATE-----", StringComparison.Ordinal);
            if (end < 0) continue;
            var certificate = new X509Certificate(Convert.FromBase64String(part.Substring(0, end)));
            X509StoreManager.LocalMachine.TrustedRoot.Import(certificate);
            X509StoreManager.NewLocalMachine.TrustedRoot.Import(certificate);
            count++;
        }
        if (count == 0) throw new InvalidOperationException("System CA bundle contains no certificates");
        Console.WriteLine("Imported {0} system roots into Mono stores", count);
    }
}
