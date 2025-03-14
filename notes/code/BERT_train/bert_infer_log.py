import torch
from transformers import BertTokenizer, BertForQuestionAnswering
import json
from tqdm import tqdm
import time
import os
import logging
formatter = logging.Formatter('%(message)s')
from jtop import jtop
import sys
import csv
import multiprocessing
from torch.utils.data import DataLoader, TensorDataset, RandomSampler
from torchvision import transforms
import pandas as pd
DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
import json


def setup_logger(name, log_file, level=logging.INFO):
    """To setup as many loggers as you want"""
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

def start_logging(filename, iostats_filename, memstats_filename, swapstats_filename, cpufreqstats_filename, gpufreqstats_filename, emcstats_filename, ramstats_filename, external_device, reference_time):
    print("jtop logging started")
    output = pd.DataFrame()
    output_cpufreqstats = pd.DataFrame()
    output_gpufreqstats = pd.DataFrame()
    output_emcstats = pd.DataFrame()
    output_ramstats = pd.DataFrame()
    with jtop() as jetson:
        tegrastats_entry = jetson.stats
        tegrastats_entry['log_time'] = str(time.time() - reference_time)
        output = pd.concat([output,pd.DataFrame([tegrastats_entry])], ignore_index=True)
        output.to_csv(filename, index=False)

        cpufreqstats_entry = jetson.cpu
        cpufreqstats_entry['log_time'] = str(time.time() - reference_time)
        output_cpufreqstats = pd.concat([output_cpufreqstats,pd.DataFrame([cpufreqstats_entry])], ignore_index=True)
        output_cpufreqstats.to_csv(cpufreqstats_filename, index=False)

        gpufreqstats_entry = jetson.gpu
        gpufreqstats_entry['log_time'] = str(time.time() - reference_time)
        output_gpufreqstats = pd.concat([output_gpufreqstats,pd.DataFrame([gpufreqstats_entry])], ignore_index=True)
        output_gpufreqstats.to_csv(gpufreqstats_filename, index=False)

        emcstats_entry = jetson.emc
        emcstats_entry['log_time'] = str(time.time() - reference_time)
        output_emcstats = pd.concat([output_emcstats,pd.DataFrame([emcstats_entry])], ignore_index=True)
        output_emcstats.to_csv(emcstats_filename, index=False)

        ramstats_entry = jetson.ram
        ramstats_entry['log_time'] = str(time.time() - reference_time)
        output_ramstats = pd.concat([output_ramstats,pd.DataFrame([ramstats_entry])], ignore_index=True)
        output_ramstats.to_csv(ramstats_filename, index=False)

    with jtop() as jetson:
        while jetson.ok():
            tegrastats_entry = jetson.stats
            tegrastats_entry['log_time'] = str(time.time() - reference_time)
            output = pd.concat([output, pd.DataFrame([tegrastats_entry])], ignore_index=True)

            cpufreqstats_entry = jetson.cpu
            cpufreqstats_entry['log_time'] = str(time.time() - reference_time)
            output_cpufreqstats = pd.concat([output_cpufreqstats, pd.DataFrame([cpufreqstats_entry])],
                                            ignore_index=True)

            gpufreqstats_entry = jetson.gpu
            gpufreqstats_entry['log_time'] = str(time.time() - reference_time)
            output_gpufreqstats = pd.concat([output_gpufreqstats, pd.DataFrame([gpufreqstats_entry])],
                                            ignore_index=True)

            emcstats_entry = jetson.emc
            emcstats_entry['log_time'] = str(time.time() - reference_time)
            output_emcstats = pd.concat([output_emcstats, pd.DataFrame([emcstats_entry])], ignore_index=True)

            ramstats_entry = jetson.ram
            ramstats_entry['log_time'] = str(time.time() - reference_time)
            output_ramstats = pd.concat([output_ramstats, pd.DataFrame([ramstats_entry])], ignore_index=True)

            io_output = os.popen("iostat -xy 1 1 -d " + external_device +
                                 " | awk 'NR>3{ for (x=2; x<=16; x++) {  printf\"%s \", $x}}' | sed 's/ /,/g'| sed 's/,*$//g'")
            io_output = io_output.read()+","+str(time.time() - reference_time)
            iostats_filename.info(io_output)

            mem_output = os.popen(
                "free -mh | awk 'NR==2{for (x=2;x<=7;x++){printf\"%s \", $x}}' | sed 's/ /,/g'| sed 's/,*$//g'")
            mem_output = mem_output.read()+","+str(time.time() - reference_time)
            memstats_filename.info(mem_output)

            swap_output = os.popen(
                "free -mh | awk 'NR==3{for (x=2;x<=4;x++){printf\"%s \", $x}}' | sed 's/ /,/g'| sed 's/,*$//g'")
            swap_output = swap_output.read()+","+str(time.time() - reference_time)
            swapstats_filename.info(swap_output)

            output.to_csv(filename,index=False, mode='a', header=False)
            output = pd.DataFrame()

            output_cpufreqstats.to_csv(cpufreqstats_filename,index=False, mode='a', header=False)
            output_cpufreqstats = pd.DataFrame()
            
            output_gpufreqstats.to_csv(gpufreqstats_filename,index=False, mode='a', header=False)
            output_gpufreqstats = pd.DataFrame()

            output_emcstats.to_csv(emcstats_filename,index=False, mode='a', header=False)
            output_emcstats = pd.DataFrame()

            output_ramstats.to_csv(ramstats_filename,index=False, mode='a', header=False)
            output_ramstats = pd.DataFrame()


def inference(model, dataloader, epoch_fname, fetch_fname, compute_fname, vmtouch_fname, dataset_outer_folder, reference_time, epochs):
    vmtouch_dir = os.path.join(dataset_outer_folder, 'vmtouch_output/')
    start1 = torch.cuda.Event(enable_timing=True)
    end1 = torch.cuda.Event(enable_timing=True)
    start2 = torch.cuda.Event(enable_timing=True)
    end2 = torch.cuda.Event(enable_timing=True)
    start3 = torch.cuda.Event(enable_timing=True)
    end3 = torch.cuda.Event(enable_timing=True)
    epoch_count = 0

    vmtouch_output = os.popen(r"vmtouch -f " + vmtouch_dir +
                              r" | sed 's/^.*://' | sed -z 's/\n/,/g' | sed 's/\s\+/,/g' | sed 's/,\{2,\}/,/g' | sed -e 's/^.\(.*\).$/\1/'")
    vmtouch_output = vmtouch_output.read()+","+str(time.time() - reference_time)
    vmtouch_fname.info(vmtouch_output)
    os.system('sudo bash ./drop_caches.sh')
    img_idx = batch_size - 1
    e2e_first_batch = 0
    stabilization_time = 5
    start_time = time.time()
    
    for _ in range(epochs):
        print('Epoch: ' + str(_) + ' Begins')
        start1.record()  # mb epoch time starts
        start2.record()  # fetch time per batch starts
        batch_count = 0
        with torch.no_grad():
            for batch in tqdm(dataloader):
                if batch_count == 0:
                    pass
                else:
                    if batch_count == 1:
                        batch_start_time = time.time()                    
                    if batch_start_time is not None and time.time() - batch_start_time > stabilization_time and batch_count > 50:
                        break
                batch_count += 1
                

                input_ids, attention_mask, token_type_ids = [item.to(DEVICE) for item in batch]               
                end2.record()  # fetch time per batch ends
                torch.cuda.synchronize()    # note: this line was not present before. I have added it since we need to synchronize
                start3.record()  # compute time per batch starts
                outputs = model(input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids)
                start_logits, end_logits = outputs.start_logits.to('cuda'), outputs.end_logits.to('cuda')
                # Convert logit scores to text (if required)
                for i in range(len(start_logits)):
                    start = torch.argmax(start_logits[i])
                    end = torch.argmax(end_logits[i])
                    answer_text = tokenizer.convert_tokens_to_string(tokenizer.convert_ids_to_tokens(input_ids[i][start:end+1]))
                    # print(answer_text)
                end3.record()  # compute time per batch ends
                torch.cuda.synchronize()
                end1.record()
                torch.cuda.synchronize()

                fetch_fname.info(str(_) + "," + str(batch_count) + "," + "null" + "," + str(
                    start2.elapsed_time(end2)) + "," + str(time.time() - reference_time))
                compute_fname.info(str(_) + "," + str(batch_count) + "," + "null" + "," + str(
                    start3.elapsed_time(end3)) + "," + str(time.time() - reference_time))
                epoch_fname.info(str(_) + "," + "null" + "," + "\"" + ":" + "\"" + "," + "null" +
                    "," + str(start1.elapsed_time(end1)) + "," + str(time.time() - reference_time))
                
                # uncomment this while running infer_only
                # if(img_idx == bsToImgIdx[batch_size]):
                #     p2.terminate()
                #     sys.exit()
                
                start1.record()
                start2.record()  # fetch time per batch starts

        print('Epoch: ' + str(_) + ' Ends')
        epoch_count += 1

    vmtouch_output = os.popen(r"vmtouch -f " + vmtouch_dir +
                              r" | sed 's/^.*://' | sed -z 's/\n/,/g' | sed 's/\s\+/,/g' | sed 's/,\{2,\}/,/g' | sed -e 's/^.\(.*\).$/\1/'")
    vmtouch_output = vmtouch_output.read()+","+str(time.time() - reference_time)
    vmtouch_fname.info(vmtouch_output)

# with open("dev-v2.0.json", 'r') as f:
#     squad_val_data = json.load(f)['data']


# def prepare_data(data):
#     questions, contexts, answers = [], [], []
#     for article in data:
#         for paragraph in article['paragraphs']:
#             context = paragraph['context']
#             for qa in paragraph['qas']:
#                 question = qa['question']
#                 answer = qa['answers'][0]['text'] if qa['answers'] else ''
#                 questions.append(question)
#                 contexts.append(context)
#                 answers.append(answer)
#     return questions, contexts, answers


# time1 = time.time()
# questions, contexts, answers = prepare_data(squad_val_data)

tokenizer = BertTokenizer.from_pretrained('bert-large-uncased')
# encoding = tokenizer(contexts, questions, truncation=True, padding=True, return_tensors='pt')
# print("Data encoding time: ",time.time()-time1)


def main(dataset_outer_folder, no_workers, pf_factor, epoch_fname, fetch_fname, compute_fname, vmtouch_fname, reference_time, batch_size, epochs):

    with open("preprocessed_infer.json", 'r') as f:
        data = json.load(f)
        questions, contexts, answers = data["questions"], data["contexts"], data["answers"]       
    encoding = torch.load("tokenized_infer.pt")
    model = BertForQuestionAnswering.from_pretrained('bert-large-uncased')
    dataset = TensorDataset(encoding['input_ids'], encoding['attention_mask'], encoding['token_type_ids'])
    dataloader = DataLoader(dataset, batch_size=16,sampler=RandomSampler(dataset),num_workers=no_workers)

    print('Reference Time is', str(reference_time))
    print('No. of testing batches = ' + str(len(dataloader)))
    print('No of workers is ' + str(no_workers))
    print('Prefetch factor is ' + str(pf_factor))
    print('Batch size is ', str(batch_size))
    model.eval()
    model.to(DEVICE)
    inference(model, dataloader, epoch_fname, fetch_fname, compute_fname,
              vmtouch_fname, dataset_outer_folder, reference_time, epochs=epochs)

if __name__ == "__main__":
    dataset_outer_folder = sys.argv[1]
    num_workers = int(sys.argv[2])
    prefetch_factor = int(sys.argv[3])
    external_device = sys.argv[4]
    batch_size = int(sys.argv[5])
    file_prefix = 'mn_'+'nw' + str(num_workers) + '_pf'+str(prefetch_factor)
    epochs = 1

    logger_fetch = setup_logger("logger_fetch", file_prefix + "_fetch.csv")

    logger_compute = setup_logger(
        "logger_compute", file_prefix + "_compute.csv")
    logger_e2e = setup_logger("logger_e2e", file_prefix + "_epoch_stats.csv")
    logger_vmtouch = setup_logger(
        "logger_vmtouch", file_prefix+"_vmtouch_stats.csv")

    logger_iostats = setup_logger(
        "logger_iostats", file_prefix+"_io_stats.csv")
    logger_memstats = setup_logger(
        "logger_memstats", file_prefix+"_mem_stats.csv")
    logger_swapstats = setup_logger(
        "logger_swapstats", file_prefix+"_swap_stats.csv")

    logger_fetch.info('epoch,batch_idx,fetchtime,fetchtime_ms,log_time')
    logger_compute.info('epoch,batch_idx,computetime,computetime_ms,log_time')
    logger_e2e.info('epoch,time,loss,accuracy,epochtime_ms,log_time')
    logger_vmtouch.info(
        'files,directories,resident_pages,resident_pages_size,resident_pages_%,elapsed,redundant,log_time')

    logger_iostats.info(
        'r/s,w/s,rkB/s,wkB/s,rrqm/s,wrqm/s,%rrqm,%wrqm,r_await,w_await,aqu-sz,rareq-sz,wareq-sz,svctm,%util,log_time')
    logger_memstats.info(
        'total,used,free,shared,buff/cache,available,log_time')
    logger_swapstats.info('total,used,free,log_time')

    with open(file_prefix+'_io_stats.csv', 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['r/s', 'w/s', 'rkB/s', 'wkB/s', 'rrqm/s', 'wrqm/s', '%rrqm', '%wrqm',
                        'r_await', 'w_await', 'aqu-sz', 'rareq-sz', 'wareq-sz', 'svctm', '%util', 'log_time'])
    with open(file_prefix+'_mem_stats.csv', 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['total', 'used', 'free', 'shared',
                        'buff/cache', 'available', 'log_time'])
    with open(file_prefix+'_swap_stats.csv', 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['total', 'used', 'free', 'log_time'])
    reference_time = time.time()
    p2 = multiprocessing.Process(target=start_logging, args=[file_prefix+'_tegrastats.csv', logger_iostats, logger_memstats, logger_swapstats, file_prefix +
                                 '_cpufreq_stats.csv', file_prefix+'_gpufreq_stats.csv', file_prefix+'_emc_stats.csv', file_prefix+'_ram_stats.csv', external_device, reference_time])
    p2.start()
    try:
        main(dataset_outer_folder, num_workers, prefetch_factor, logger_e2e,
             logger_fetch, logger_compute, logger_vmtouch, reference_time, batch_size, epochs)
    except ():
        print("hit an exception")
        print()
        p2.terminate()

    p2.terminate()
