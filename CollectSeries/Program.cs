using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using VMS.TPS.Common.Model.API;
using VMS.TPS.Common.Model.Types;
using System.IO;
using System.Data;
using System.Threading;
using System.Windows;
using System.Text.RegularExpressions;
using EvilDICOM.Core;
using EvilDICOM.Core.Element;
using EvilDICOM.Core.Helpers;
using EvilDICOM.Network;
using EvilDICOM.Network.DIMSE;
using EvilDICOM.Network.Enums;
using EvilDICOM.Network.DIMSE.IOD;
using System.Runtime.ConstrainedExecution;
//using EvilDICOM.Core.Modules;
using System.Runtime.Remoting;
using System.Windows.Documents;

class PatientPlanInfo
{
    public string PtID { get; set; }
    public string Course { get; set; }
    public string PlanID { get; set; }
}

class CTPhaseData
{
    public string SeriesId { get; set; }
    public string SeriesUID { get; set; }
    public string RefUID { get; set; }
    public List<string> UnetStructureIds { get; set; } = new List<string>();
    public List<string> UnetStructureSetIds { get; set; } = new List<string>();
    public List<string> UnetStructureSetUIDs { get; set; } = new List<string>();
}

class PatientCTData
{
    public string PatientId { get; set; }
    public string Course { get; set; }
    public string StudyUID { get; set; }
    public Dictionary<string, CTPhaseData> PhaseData { get; set; } = new Dictionary<string, CTPhaseData>
    {
        { "CT_0", new CTPhaseData() },
        { "CT_50", new CTPhaseData() }
    };
}

class StoragePath
{
    public string CurrentStoragePath { get; set; }
}



namespace CollectSeries
{
    class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            try
            {
                using (VMS.TPS.Common.Model.API.Application app = VMS.TPS.Common.Model.API.Application.CreateApplication())
                {

                    int numPatients = 1; // number of patients to run the script on. Set to -1 to go through the whole list.

                    Console.WriteLine("Starting program...\n");
                    string csvPath = "I:\\PHYSICS\\Ben\\Filtered_unet_plans.csv";
                    Console.WriteLine("Opening: {0}...\n", csvPath);
                    List<PatientPlanInfo> patientPlans = GetPatientList(csvPath, numPatients);

                    List<PatientCTData> allPatientData = Execute(app, patientPlans);
                    Console.WriteLine($"Length of Patient Data Structure: {allPatientData.Count}\n________\n");

                    DisplayPatientData(allPatientData);


                    // Starting Dicom Daemon

                    // --- DICOM DAEMON CONFIGURATION --- \\
                    string serverAE = "VMSAPI";
                    string serverIP = "172.26.120.74";
                    int serverPort = 51402;
                    string clientAE = "MUHC-BASE-17";
                    int clientPort = 51402;
                    string storagePath = "I://PHYSICS//Ben//TEMP";
                    // ----------------------------------- \\

                    Console.WriteLine("\n\nStarting Dicom Daemon Section\n\n");

                    // Ping Daemon (C-ECHO)
                    var (daemon, local, client, receiver, pathHolder) = InitializeDICOMDaemon(serverAE, serverIP, serverPort, clientAE, clientPort, storagePath);

                    // export patient data
                    foreach (var patient in allPatientData)
                    {   
                        // updating storage path
                        pathHolder.CurrentStoragePath = Path.Combine(storagePath, patient.PatientId);
                        Directory.CreateDirectory(pathHolder.CurrentStoragePath);
                        ExportPatientDicomData(patient, storagePath, daemon, local, client, receiver, pathHolder);
                    }

                }
            }
            catch (Exception e)
            {
                Console.Error.WriteLine(e.ToString());
                Console.ReadKey();
            }
        }


        static (Entity daemon, Entity local, DICOMSCU client, DICOMSCP receiver, StoragePath pathHolder) InitializeDICOMDaemon(
                                                                                                                string daemonAE, string daemonIP, int daemonPort,
                                                                                                                string localAE, int localPort,
                                                                                                                string initialPath)
        {
            var pathHolder = new StoragePath { CurrentStoragePath = initialPath };

            var daemon = new Entity(daemonAE, daemonIP, daemonPort);
            var local = Entity.CreateLocal(localAE, localPort);
            var client = new DICOMSCU(local);
            var receiver = new DICOMSCP(local);

            receiver.SupportedAbstractSyntaxes = AbstractSyntax.ALL_RADIOTHERAPY_STORAGE;

            receiver.DIMSEService.CStoreService.CStorePayloadAction = (dcm, asc) =>
            {
                Console.WriteLine("Writing file...");
                var fullpath = Path.Combine(pathHolder.CurrentStoragePath, dcm.GetSelector().SOPInstanceUID.Data + ".dcm");
                Console.WriteLine($" Writing file {fullpath}... ");
                dcm.Write(fullpath);
                return true;
            };
            receiver.ListenForIncomingAssociations(true);

            Console.WriteLine("Initializing DICOM SCU connection...");
            Console.WriteLine($"  Local AE:   {local.AeTitle}");
            Console.WriteLine($"  Local IP:   {local.IpAddress}:{local.Port}");
            Console.WriteLine($"  Daemon AE:  {daemon.AeTitle}");
            Console.WriteLine($"  Daemon IP:  {daemon.IpAddress}:{daemon.Port}\n");

            Console.Write("Pinging daemon...");

            bool echoSuccess = client.Ping(daemon);

            if (echoSuccess)
            {
                Console.WriteLine("\rC-ECHO Success: Connection to DICOM Daemon is active.\n");
            }
            else
            {
                Console.WriteLine("\rC-ECHO Failed: Could not reach DICOM Daemon.\n");
            }

            return (daemon, local, client, receiver, pathHolder);
        }



        static void ExportPatientDicomData(PatientCTData patient,
                                            string exportRoot,
                                            Entity daemon,
                                            Entity local,
                                            DICOMSCU client,
                                            DICOMSCP receiver,
                                            StoragePath pathHolder)
        {
            Console.WriteLine($"Processing patient: {patient.PatientId}");

            // Set storage path for this patient
            pathHolder.CurrentStoragePath = Path.Combine(exportRoot, $"{patient.PatientId}_{patient.Course}");
            Directory.CreateDirectory(pathHolder.CurrentStoragePath);

            // Write GTV structure IDs to GTV.txt
            string gtvFilePath = Path.Combine(pathHolder.CurrentStoragePath, "GTV.txt");
            using (var writer = new StreamWriter(gtvFilePath))
            {
                foreach (var phase in patient.PhaseData.Values)
                {
                    foreach (var structId in phase.UnetStructureIds)
                    {
                        writer.WriteLine(structId);
                    }
                }
            }

            var finder = client.GetCFinder(daemon);
            var mover = client.GetCMover(daemon);
            ushort msgId = 1;

            foreach (var phaseKey in new[] { "CT_0", "CT_50" })
            {
                var phase = patient.PhaseData[phaseKey];
                if (string.IsNullOrWhiteSpace(phase.SeriesUID))
                {
                    Console.WriteLine($"  Skipping {phaseKey} - Series UID missing.");
                    continue;
                }

                // Create patient/phase directory (optional, since storage path changed)
                string phaseDir = Path.Combine(pathHolder.CurrentStoragePath, phaseKey);
                Directory.CreateDirectory(phaseDir);

                // Locate study and series
                var study = finder.FindStudies(patient.PatientId).FirstOrDefault(s => s.StudyInstanceUID == patient.StudyUID);
                if (study == null)
                {
                    Console.WriteLine($"  Study not found for UID: {patient.StudyUID}");
                    continue;
                }

                var seriesList = finder.FindSeries(study);
                var ctSeries = seriesList.FirstOrDefault(s => s.SeriesInstanceUID == phase.SeriesUID);
                if (ctSeries == null)
                {
                    Console.WriteLine($"  CT Series not found for UID: {phase.SeriesUID}");
                    continue;
                }
                else Console.WriteLine($"     --> C-FIND successfully retrieved series {ctSeries.SeriesInstanceUID}");

                // Export CT images with C-MOVE
                var response = mover.SendCMove(ctSeries, local.AeTitle, ref msgId);
                Console.WriteLine($"CT [{phaseKey}] Series C-MOVE:");
                Console.WriteLine($"  Completed: {response.NumberOfCompletedOps}");
                Console.WriteLine($"  Failed:    {response.NumberOfFailedOps}");
                Console.WriteLine($"  Remaining: {response.NumberOfRemainingOps}");
                Console.WriteLine($"  Warnings:  {response.NumberOfWarningOps}");

                // Export RTStruct if available
                if (phase.UnetStructureSetUIDs.Count > 0)
                {
                    string targetRTStructUID = phase.UnetStructureSetUIDs[0]; // use first UID

                    var rtstructSeries = seriesList
                        .Where(s => s.Modality == "RTSTRUCT")
                        .FirstOrDefault(s => finder.FindImages(s).Any(img => img.SOPInstanceUID == targetRTStructUID));

                    if (rtstructSeries != null)
                    {
                        var rtstructImage = finder.FindImages(rtstructSeries)
                            .FirstOrDefault(img => img.SOPInstanceUID == targetRTStructUID);

                        if (rtstructImage != null)
                        {
                            var responseRT = mover.SendCMove(rtstructImage, local.AeTitle, ref msgId);
                            Console.WriteLine($"RTSTRUCT C-MOVE:");
                            Console.WriteLine($"  Completed: {responseRT.NumberOfCompletedOps}");
                            Console.WriteLine($"  Failed:    {responseRT.NumberOfFailedOps}");
                            Console.WriteLine($"  Remaining: {responseRT.NumberOfRemainingOps}");
                            Console.WriteLine($"  Warnings:  {responseRT.NumberOfWarningOps}");
                        }
                        else
                        {
                            Console.WriteLine($"  RTStruct SOPInstanceUID {targetRTStructUID} not found in series.");
                        }
                    }
                    else
                    {
                        Console.WriteLine($"  RTStruct series with UID {targetRTStructUID} not found.");
                    }
                }
                else
                {
                    Console.WriteLine($"  No RTStruct UID found for phase {phaseKey}");
                }
            }

            Console.WriteLine($"Completed export for patient: {patient.PatientId}\n");
        }


        static void DisplayPatientData(List<PatientCTData> allPatientData)
        {
            foreach (var patient in allPatientData)
            {
                Console.WriteLine($"Patient ID: {patient.PatientId}");
                Console.WriteLine($"Study UID:  {patient.StudyUID}");

                foreach (var phaseKey in new[] { "CT_0", "CT_50" })
                {
                    if (!patient.PhaseData.ContainsKey(phaseKey))
                    {
                        Console.WriteLine($"  {phaseKey}: No data found.");
                        continue;
                    }

                    var phase = patient.PhaseData[phaseKey];
                    Console.WriteLine($"  {phaseKey}:");
                    Console.WriteLine($"    Series ID: {phase.SeriesId}");
                    Console.WriteLine($"    Series UID: {phase.SeriesUID}");
                    Console.WriteLine($"    Ref UID:    {phase.RefUID}");

                    if (phase.UnetStructureIds.Count == 0)
                    {
                        Console.WriteLine("    UNET Structures: None");
                    }
                    else
                    {
                        Console.WriteLine("    UNET Structures:");
                        for (int i = 0; i < phase.UnetStructureIds.Count; i++)
                        {
                            string structId = phase.UnetStructureIds[i];
                            string structSetId = i < phase.UnetStructureSetIds.Count ? phase.UnetStructureSetIds[i] : "N/A";
                            string structSetUID = i < phase.UnetStructureSetUIDs.Count ? phase.UnetStructureSetUIDs[i] : "N/A";

                            Console.WriteLine($"      Structure ID: {structId}");
                            Console.WriteLine($"      Structure Set ID: {structSetId}");
                            Console.WriteLine($"      Structure Set UID: {structSetUID}\n");
                        }
                    }
                }

                Console.WriteLine(new string('-', 50));
            }
        }



        static List<PatientPlanInfo> GetPatientList(string csvPath, int numPatients)
        {
            var patientPlans = new List<PatientPlanInfo>();

            using (var reader = new StreamReader(csvPath))
            {
                string headerLine = reader.ReadLine(); // skip header

                int i = 0;
                while (!reader.EndOfStream && (i < numPatients || numPatients == -1))
                {
                    i++;
                    var line = reader.ReadLine();
                    var values = line.Split(',');

                    // Adjust order
                    var info = new PatientPlanInfo
                    {
                        PtID = values[0].Trim().PadLeft(7, '0'), // to ensure leading '0's are in the patient IDs
                        Course = values[2].Trim(),
                        PlanID = values[3].Trim()
                    };

                    patientPlans.Add(info);
                }

                reader.Close();
            }

            return patientPlans;
        }

        static List<PatientCTData> Execute(VMS.TPS.Common.Model.API.Application app, List<PatientPlanInfo> patientPlans)
        {
            Patient patient = null;
            Course course = null;
            PlanSetup plan = null;
            Study study = null;
            IEnumerable<Series> studylist = null;
            List<PatientCTData> allPatientsData = new List<PatientCTData>(); // creating data structure to store all patient data
            List<Series> patientSeries = new List<Series>();
            List<Structure> unetStructs = new List<Structure>();
            Series phase0 = null, phase1 = null;
            bool hasphase0 = false, hasphase1 = false;
            int i = 0;

            // Regex expressions
            Regex phase0Regex = new Regex(@"^CT_?0(_|$)"); // starts with 'CT'; optional '_'; required '0'; either followed by '_' or ends.
            Regex phase1Regex = new Regex(@"^CT_?50(_|$)");
            Regex struct0Regex = new Regex(@"^UNET\d_0$"); // starts with 'UNET'; some digit; underscore; 0 to end
            Regex struct1Regex = new Regex(@"^UNET\d_50$"); // starts with 'UNET'; some digit; underscore; 50 to end

            Console.WriteLine("Searching through structure sets...");
            foreach (var planInfo in patientPlans)
            {
                // Open the plan
                patient = app.OpenPatientById(planInfo.PtID);
                if (patient == null)
                {
                    MessageBox.Show($"Patient {planInfo.PtID} missing");    
                    continue;
                }

                //Console.WriteLine("Patient: {0}", patient.Id);
                course = patient.Courses.Where(c => c.Id == planInfo.Course).Single();
                plan = course.PlanSetups.Where(p => p.Id == planInfo.PlanID).Single();
                study = plan.Series.Study;
                studylist = study.Series;

                PatientCTData patientCT = new PatientCTData();
                patientCT.PatientId = patient.Id;
                patientCT.Course = course.Id;
                patientCT.StudyUID = study.UID;

                foreach (Series item in studylist)
                {
                    try
                    {
                        foreach (Image image in item.Images)
                        {
                            //if (image.Id.StartsWith("CT0") || image.Id.StartsWith("CT_0"))
                            if (phase0Regex.IsMatch(image.Id))
                            {
                                if (hasphase0) { Console.WriteLine($"!! THERE ARE SEVERAL CT_0s for patient {patient.Id} !!"); }
                                hasphase0 = true;
                                phase0 = item;
                            }
                            //else if (image.Id.StartsWith("CT50") || image.Id.StartsWith("CT_50"))
                            else if (phase1Regex.IsMatch(image.Id))
                            {
                                if (hasphase1) { Console.WriteLine($"!! THERE ARE SEVERAL CT_50s for patient {patient.Id} !!"); }
                                hasphase1 = true;
                                phase1 = item;
                            }
                        } // loop through all images in Series
                    }
                    catch
                    {
                        continue;
                    } // series doesn't contain images
                } // loop through all Series in Study

                // Once all series are searched, we check if both CT_0 and CT_50 are included
                if (hasphase0 && hasphase1)
                {
                    //Console.WriteLine($"CT_0 in series {phase0.Id}");
                    //Console.WriteLine($"CT_50 in series {phase1.Id}");
                    //patientSeries.Add(phase0);
                    patientCT.PhaseData["CT_0"].SeriesId = phase0.Id;
                    patientCT.PhaseData["CT_0"].SeriesUID = phase0.UID;
                    Console.WriteLine(++i);
                    //patientSeries.Add(phase1);
                    patientCT.PhaseData["CT_50"].SeriesId = phase1.Id;
                    patientCT.PhaseData["CT_50"].SeriesUID = phase1.UID;
                    Console.WriteLine(++i);
                    //MessageBox.Show($"UnetStructs length: {unetStructs.Count}\nPatient number: {patient.Id}");


                    foreach (var set in patient.StructureSets)
                    {
                        var refUID = set.Image?.Series?.UID; // referenced series (i.e., series that structure set belongs to)
                        
                        foreach (Structure structure in set.Structures)
                        {
                            if (struct0Regex.IsMatch (structure.Id) && refUID == phase0.UID)
                            {
                                patientCT.PhaseData["CT_0"].UnetStructureIds.Add(structure.Id);
                                patientCT.PhaseData["CT_0"].UnetStructureSetIds.Add(set.Id);
                                patientCT.PhaseData["CT_0"].UnetStructureSetUIDs.Add(set.UID);
                                patientCT.PhaseData["CT_0"].RefUID = refUID;
                            }
                            else if (struct1Regex.IsMatch(structure.Id) && refUID == phase1.UID)
                            {
                                patientCT.PhaseData["CT_50"].UnetStructureIds.Add(structure.Id);
                                patientCT.PhaseData["CT_50"].UnetStructureSetIds.Add(set.Id);
                                patientCT.PhaseData["CT_50"].UnetStructureSetUIDs.Add(set.UID);
                                patientCT.PhaseData["CT_50"].RefUID = refUID;
                            }

                        } // looping through structure set to find UNET structures

                        // Console.WriteLine($"Set id: {patient.StructureSets.Id}\nseries id: {patient.StructureSets.Image.Series.UID}\nphase 0 uid: {phase0?.UID}\nphase 50 uid: {phase1?.UID}\n");

                    } // looping through structure sets
                }
                else if (hasphase0 != hasphase1) 
                    Console.WriteLine($"\nMissing one of the CT phases patient: {patient.Id}\n");

                hasphase0 = hasphase1 = false;

                allPatientsData.Add(patientCT);
                app.ClosePatient();

            } // looping through patients
            Console.WriteLine(new string('_', 50));

            return allPatientsData;
        }
    } // class Program

} // namespace