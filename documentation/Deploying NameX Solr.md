
*NOTE: this expects you to already have:
1. your local gcloud configured
2. permissions to connect and update the GCP environment
3. firewall permissions for viewing and connecting to VMs in the GCP environment
4. the current LEADER / FOLLOWER VM names running in the GCP environment (these will be removed)
5. your local OpenShift CLI configured / logged in
6. permissions to connect and update the OCP environment
7. local docker running

Set initial variables:
```
ENV=
```

```
PROJECT=
```

```
PROJECT_ID=$PROJECT-$ENV
```

### Building the new images (for DEV only)

1. Build the solr docker images for the leader / follower nodes:  
	```
	make build
	```
2. Configure docker auth for the artifactory repo in the gcp zone if you haven't done so before:
    ```
    gcloud auth configure-docker northamerica-northeast1-docker.pkg.dev
	```
3. Tag the leader and follower images in preparation for the GCP atrifactory repo push:
   ```
   docker tag namex-solr-leader northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-leader:dev
	```
	```
   docker tag namex-solr-follower northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-follower:dev
	```
4. Push the images to the GCP artifiactory repo:
   ```
   docker push northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-leader:dev
	```

	```
   docker push northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-follower:dev
	```

### Tagging the images (for TEST / PROD only)

*Update to 'test' for a prod deploy*
```
SOURCE_TAG=dev
```

```
gcloud artifacts docker tags add northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-leader:$SOURCE_TAG northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-leader:$ENV
```

```
gcloud artifacts docker tags add northamerica-northeast1-docker.pkg.dev/$PROJECT-dev/temp-namex/namex-solr-follower:$SOURCE_TAG northamerica-northeast1-docker.pkg.dev/$PROJECT--tools/temp-namex/namex-solr-follower:$ENV
```

### Deploying the new instances

1. Set the NEW leader and follower instance names:
   ```
   NEW_LEADER_VM=namex-solr-leader-$ENV-$(date -u +"%Y-%m-%d--%H%M%S")
   ```
   
   ```
   NEW_FOLLOWER_VM=namex-solr-follower-$ENV-$(date -u +"%Y-%m-%d--%H%M%S")
   ```
2. Set the OLD leader name (for later):
   ```
   OLD_LEADER_VM=$(gcloud compute instances list --format="value(name)" --filter name:namex-solr-leader-$ENV --project=$PROJECT_ID)
   ```
3. Set the OLD follower name (for later)
   ```
   OLD_FOLLOWER_VM=$(gcloud compute instances list --format="value(name)" --filter name:namex-solr-follower-$ENV --project=$PROJECT_ID)
   ```
4. Create a new namex-solr LEADER instance:
   ```
   gcloud compute instances create $NEW_LEADER_VM --source-instance-template namex-solr-leader-vm-tmpl-$ENV --zone northamerica-northeast1-a --project $PROJECT_ID
	```
5. Set NEW leader internal IP
   ```
   NEW_LEADER_INTERNAL_IP=$(gcloud compute instances list --format="value(INTERNAL_IP)" --filter name:$NEW_LEADER_VM --project=$PROJECT_ID)
   ```
6. Add the NEW leader instance to the leader network:
    ```
    gcloud compute instance-groups unmanaged add-instances namex-solr-leader-grp-$ENV --zone northamerica-northeast1-a --instances $NEW_LEADER_VM --project $PROJECT_ID
    ```
7. Remove the OLD leader from the leader network (*NOTE: after this point, updates will not be seen in the search until the new solr is up*):
    ```
    gcloud compute instance-groups unmanaged remove-instances namex-solr-leader-grp-$ENV --zone northamerica-northeast1-a --instances $OLD_LEADER_VM --project $PROJECT_ID
    ```
8. Run the Importer
   - manually run the importer (it will load all the data inside the new instance)
1. Create the new FOLLOWER instance:
    ```
    gcloud compute instances create $NEW_FOLLOWER_VM --source-instance-template namex-solr-follower-vm-tmpl-$ENV --zone northamerica-northeast1-a --project $PROJECT_ID
    ```
2. Set the new FOLLOWER instance *external* IP:
    ```
    NEW_FOLLOWER_EXTERNAL_IP=$(gcloud compute instances list --format="value(EXTERNAL_IP)" --filter name:$NEW_FOLLOWER_VM --project=$PROJECT_ID)
    ```
3. Update the new FOLLOWER instance config for the cluster:
   *NOTE: if the connection is refused try waiting a couple minutes and then retry (the solr core is probably still booting up). If it is still refused make sure you have firewall permissions to access VM IPs*
    ```
    curl -X POST -H 'Content-type: application/json' -d '{"set-user-property":{"solr.leaderUrl": "http://'${NEW_LEADER_INTERNAL_IP}':8983/solr/namex_search"}}' http://$NEW_FOLLOWER_EXTERNAL_IP:8983/solr/namex_search_follower/config/requestHandler
    ```
4. Wait for the new FOLLOWER instance to finish copying the leader index *(~tbd mins for prod)* / check logs for errors: *<NEW_FOLLOWER_EXTERNAL_IP>:8983/solr/namex_search_follower/replication*
5. Add the NEW follower instance to the follower network:
    ```
    gcloud compute instance-groups unmanaged add-instances namex-solr-follower-grp-$ENV --zone northamerica-northeast1-a --instances $NEW_FOLLOWER_VM --project $PROJECT_ID
    ```
6. Remove the OLD follower from the follower network:
    ```
    gcloud compute instance-groups unmanaged remove-instances namex-solr-follower-grp-$ENV --zone northamerica-northeast1-a --instances $OLD_FOLLOWER_VM --project $PROJECT_ID
    ```
7. Test out the search / check the logs. Ensure everything is working as expected. If there is an issue with the NEW instances *add the OLD instances back to their respective networks and remove or delete the NEW instances*
8. Delete the OLD instances:
    ```
    gcloud compute instances delete $OLD_FOLLOWER_VM --zone=northamerica-northeast1-a --project $PROJECT_ID
    ```
    ```
    gcloud compute instances delete $OLD_LEADER_VM --zone=northamerica-northeast1-a --project $PROJECT_ID
    ```